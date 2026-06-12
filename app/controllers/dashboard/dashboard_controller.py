from functools import partial

from app.config.db.connection import Database
from app.controllers.authentication.auth_controller import get_user_from_request
from app.http.http_server import HTTPRequest, HTTPResponse


def handle_dashboard(request: HTTPRequest, db: Database) -> HTTPResponse:
    """GET /api/dashboard - Get aggregated dashboard data"""
    user = get_user_from_request(request, db)
    if not user:
        return HTTPResponse.json({"error": "Unauthorized"}, 401)

    # Get user's classrooms
    classrooms = db.fetch_all("""
        SELECT c.id, c.name, c.code, c.mode, c.is_active, c.created_at, cp.role,
            (SELECT COUNT(*) FROM classroom_participants WHERE classroom_id = c.id) as participant_count,
            (SELECT username FROM users WHERE id = c.host_id) as host_name
        FROM classrooms c
        JOIN classroom_participants cp ON cp.classroom_id = c.id AND cp.user_id = %s
        ORDER BY c.created_at DESC
        LIMIT 10
    """, (user["id"],))

    # Get recent news across all classrooms
    news = db.fetch_all("""
        SELECT n.*, c.name as classroom_name, u.username as author_name
        FROM class_news n
        JOIN classrooms c ON c.id = n.classroom_id
        JOIN users u ON u.id = n.author_id
        JOIN classroom_participants cp ON cp.classroom_id = n.classroom_id AND cp.user_id = %s
        ORDER BY n.created_at DESC
        LIMIT 20
    """, (user["id"],))

    # Global leaderboard
    leaderboard = db.fetch_all("""
        SELECT id, username, name AS display_name,
            0 AS total_points, 0 AS streak_days
        FROM users
        ORDER BY total_points DESC
        LIMIT 10
    """)

    # User stats
    stats = db.fetch_one("""
        SELECT 
            (SELECT COUNT(*) FROM classroom_participants WHERE user_id = %s) as class_count,
            (SELECT COUNT(*) FROM quiz_answers WHERE user_id = %s AND is_correct = 1) as correct_answers,
            (SELECT COUNT(*) FROM quiz_answers WHERE user_id = %s) as total_answers
    """, (user["id"], user["id"], user["id"]))

    return HTTPResponse.json({
        "user": user,
        "classrooms": classrooms,
        "news": news,
        "leaderboard": leaderboard,
        "stats": stats or {},
    })


def handle_global_leaderboard(
    request: HTTPRequest,
    db: Database,
) -> HTTPResponse:
    """GET /api/dashboard/leaderboard - Global leaderboard"""
    leaderboard = db.fetch_all("""
        SELECT id, username, name AS display_name,
            0 AS total_points, 0 AS streak_days
        FROM users
        ORDER BY username ASC
        LIMIT 50
    """)
    return HTTPResponse.json({"leaderboard": leaderboard})


def register_dashboard_routes(server, db: Database):
    server.add_route(
        "/api/dashboard",
        "GET",
        partial(handle_dashboard, db=db),
    )
    server.add_route(
        "/api/dashboard/leaderboard",
        "GET",
        partial(handle_global_leaderboard, db=db),
    )
