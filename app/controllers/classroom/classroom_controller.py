import random
import string
from functools import partial
from app.config.db.connection import Database
from app.controllers.authentication.auth_controller import get_user_from_request
from app.http.http_server import HTTPRequest, HTTPResponse
from app.http.sse_manager import SSEManager, SSEResponse


def _generate_code(length: int = 6) -> str:
    """Generate a random classroom join code."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def handle_create_classroom(request: HTTPRequest, db: Database) -> HTTPResponse:
    """POST /api/classroom - Create a new classroom"""
    user = get_user_from_request(request, db)
    if not user:
        return HTTPResponse.json({"error": "Unauthorized"}, 401)

    try:
        data = request.json()
        name = data.get("name", "").strip()
        description = data.get("description", "")
        mode = data.get("mode", "quiz_only")  # 'quiz_only' or 'ppt_sharing'

        if not name:
            return HTTPResponse.json({"error": "Classroom name is required"}, 400)

        if mode not in ("quiz_only", "ppt_sharing"):
            mode = "quiz_only"

        # Generate unique code
        code = _generate_code()
        while db.fetch_one("SELECT id FROM classrooms WHERE code = %s", (code,)):
            code = _generate_code()

        classroom_id = db.execute(
            "INSERT INTO classrooms (name, description, code, host_id, mode) VALUES (%s, %s, %s, %s, %s)",
            (name, description, code, user["id"], mode)
        )

        # Auto-add host as participant with 'host' role
        db.execute(
            "INSERT INTO classroom_participants (classroom_id, user_id, role) VALUES (%s, %s, 'host')",
            (classroom_id, user["id"])
        )

        return HTTPResponse.json({
            "message": "Classroom created",
            "classroom": {
                "id": classroom_id,
                "name": name,
                "description": description,
                "code": code,
                "mode": mode,
                "host_id": user["id"],
            }
        }, 201)

    except Exception as e:
        print(f"[CLASSROOM] Create error: {e}")
        return HTTPResponse.json({"error": str(e)}, 500)


def handle_list_classrooms(request: HTTPRequest, db: Database) -> HTTPResponse:
    """GET /api/classroom - List all classrooms the user is part of"""
    user = get_user_from_request(request, db)
    if not user:
        return HTTPResponse.json({"error": "Unauthorized"}, 401)

    classrooms = db.fetch_all("""
        SELECT c.*, cp.role,
            (SELECT COUNT(*) FROM classroom_participants WHERE classroom_id = c.id) as participant_count,
            (SELECT username FROM users WHERE id = c.host_id) as host_name
        FROM classrooms c
        JOIN classroom_participants cp ON cp.classroom_id = c.id AND cp.user_id = %s
        ORDER BY c.created_at DESC
    """, (user["id"],))

    return HTTPResponse.json({"classrooms": classrooms})


def handle_get_classroom(
    request: HTTPRequest,
    db: Database,
    id: str = "",
) -> HTTPResponse:
    """GET /api/classroom/:id - Get classroom details"""
    user = get_user_from_request(request, db)
    if not user:
        return HTTPResponse.json({"error": "Unauthorized"}, 401)

    classroom = db.fetch_one("""
        SELECT c.*,
            (SELECT username FROM users WHERE id = c.host_id) as host_name
        FROM classrooms c WHERE c.id = %s
    """, (id,))

    if not classroom:
        return HTTPResponse.json({"error": "Classroom not found"}, 404)

    # Get participants
    participants = db.fetch_all("""
        SELECT u.id, u.username, u.name AS display_name, cp.role, cp.joined_at
        FROM classroom_participants cp
        JOIN users u ON u.id = cp.user_id
        WHERE cp.classroom_id = %s
        ORDER BY cp.role DESC, cp.joined_at ASC
    """, (id,))

    # Get quizzes
    quizzes = db.fetch_all("""
        SELECT q.*, (SELECT COUNT(*) FROM quiz_questions WHERE quiz_id = q.id) as question_count
        FROM quizzes q WHERE q.classroom_id = %s
        ORDER BY q.created_at DESC
    """, (id,))

    classroom["participants"] = participants
    classroom["quizzes"] = quizzes

    # Check user's role
    user_role = db.fetch_one(
        "SELECT role FROM classroom_participants WHERE classroom_id = %s AND user_id = %s",
        (id, user["id"])
    )
    classroom["user_role"] = user_role["role"] if user_role else None

    return HTTPResponse.json({"classroom": classroom})


def handle_join_classroom(request: HTTPRequest, db: Database) -> HTTPResponse:
    """POST /api/classroom/join - Join classroom by code"""
    user = get_user_from_request(request, db)
    if not user:
        return HTTPResponse.json({"error": "Unauthorized"}, 401)

    try:
        data = request.json()
        code = data.get("code", "").strip().upper()

        if not code:
            return HTTPResponse.json({"error": "Classroom code is required"}, 400)

        classroom = db.fetch_one(
            "SELECT * FROM classrooms WHERE code = %s",
            (code,),
        )

        if not classroom:
            return HTTPResponse.json({"error": "Invalid classroom code"}, 404)

        # Check if already a participant
        existing = db.fetch_one(
            "SELECT id FROM classroom_participants WHERE classroom_id = %s AND user_id = %s",
            (classroom["id"], user["id"])
        )
        if existing:
            return HTTPResponse.json({"error": "Already a member of this classroom"}, 409)

        db.execute(
            "INSERT INTO classroom_participants (classroom_id, user_id, role) VALUES (%s, %s, 'participant')",
            (classroom["id"], user["id"])
        )

        # Notify via SSE
        sse = SSEManager.get_instance()
        sse.publish(f"classroom_{classroom['id']}", "participant_joined", {
            "user_id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
        })

        return HTTPResponse.json({
            "message": f"Joined classroom '{classroom['name']}'",
            "classroom": {
                "id": classroom["id"],
                "name": classroom["name"],
                "code": classroom["code"],
                "mode": classroom["mode"],
            }
        })

    except Exception as e:
        print(f"[CLASSROOM] Join error: {e}")
        return HTTPResponse.json({"error": str(e)}, 500)


def handle_classroom_stream(
    request: HTTPRequest,
    db: Database,
    id: str = "",
) -> SSEResponse:
    """GET /api/classroom/:id/stream - SSE stream for classroom events"""
    user = get_user_from_request(request, db)
    user_id = user["id"] if user else None
    return SSEResponse(channel=f"classroom_{id}", user_id=user_id)


def handle_classroom_news(
    request: HTTPRequest,
    db: Database,
    id: str = "",
) -> HTTPResponse:
    """POST /api/classroom/:id/news - Post news to classroom"""
    user = get_user_from_request(request, db)
    if not user:
        return HTTPResponse.json({"error": "Unauthorized"}, 401)

    try:
        data = request.json()
        title = data.get("title", "").strip()
        content = data.get("content", "")

        if not title:
            return HTTPResponse.json({"error": "Title is required"}, 400)

        news_id = db.execute(
            "INSERT INTO class_news (classroom_id, author_id, title, content) VALUES (%s, %s, %s, %s)",
            (id, user["id"], title, content)
        )

        # Notify via SSE
        sse = SSEManager.get_instance()
        sse.publish(f"classroom_{id}", "news", {
            "id": news_id,
            "title": title,
            "content": content,
            "author": user["display_name"] or user["username"],
        })

        return HTTPResponse.json({"message": "News posted", "id": news_id}, 201)

    except Exception as e:
        return HTTPResponse.json({"error": str(e)}, 500)


def handle_get_news(
    request: HTTPRequest,
    db: Database,
    id: str = "",
) -> HTTPResponse:
    """GET /api/classroom/:id/news - Get classroom news"""
    news = db.fetch_all("""
        SELECT n.*, u.username as author_name, u.name as author_display
        FROM class_news n
        JOIN users u ON u.id = n.author_id
        WHERE n.classroom_id = %s
        ORDER BY n.created_at DESC
        LIMIT 50
    """, (id,))

    return HTTPResponse.json({"news": news})


def register_classroom_routes(server, db: Database):
    """Register classroom routes with the HTTP server."""
    server.add_route(
        "/api/classroom",
        "POST",
        partial(handle_create_classroom, db=db),
    )
    server.add_route(
        "/api/classroom",
        "GET",
        partial(handle_list_classrooms, db=db),
    )
    server.add_route(
        "/api/classroom/join",
        "POST",
        partial(handle_join_classroom, db=db),
    )
    server.add_route(
        "/api/classroom/:id",
        "GET",
        partial(handle_get_classroom, db=db),
    )
    server.add_route(
        "/api/classroom/:id/stream",
        "GET",
        partial(handle_classroom_stream, db=db),
    )
    server.add_route(
        "/api/classroom/:id/news",
        "POST",
        partial(handle_classroom_news, db=db),
    )
    server.add_route(
        "/api/classroom/:id/news",
        "GET",
        partial(handle_get_news, db=db),
    )
