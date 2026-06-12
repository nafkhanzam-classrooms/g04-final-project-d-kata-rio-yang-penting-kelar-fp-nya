import base64
import threading
from functools import partial
from app.config.db.connection import Database
from app.controllers.authentication.auth_controller import get_user_from_request
from app.http.http_server import HTTPRequest, HTTPResponse
from app.http.sse_manager import SSEManager, SSEResponse

# In-memory store for latest screen frame per classroom
_screen_frames = {}  # classroom_id -> bytes (JPEG)
_frame_lock = threading.Lock()


def handle_upload_frame(
    request: HTTPRequest,
    db: Database,
    id: str = "",
) -> HTTPResponse:
    """POST /api/classroom/:id/screen/frame - Host uploads a JPEG frame"""
    user = get_user_from_request(request, db)
    if not user:
        return HTTPResponse.json({"error": "Unauthorized"}, 401)

    frame_data = request.body
    if not frame_data:
        return HTTPResponse.json({"error": "No frame data"}, 400)

    with _frame_lock:
        _screen_frames[id] = frame_data

    # Push to viewers via SSE as base64
    b64 = base64.b64encode(frame_data).decode("ascii")
    sse = SSEManager.get_instance()
    sse.publish(f"screen_{id}", "frame", b64)

    return HTTPResponse.json({"status": "ok"})


def handle_screen_stream(
    request: HTTPRequest,
    db: Database,
    id: str = "",
) -> SSEResponse:
    """GET /api/classroom/:id/screen/stream - SSE stream for screen frames"""
    user = get_user_from_request(request, db)
    user_id = user["id"] if user else None
    return SSEResponse(channel=f"screen_{id}", user_id=user_id)


def handle_screen_status(request: HTTPRequest, id: str = "") -> HTTPResponse:
    """GET /api/classroom/:id/screen/status - Check if screen sharing is active"""
    with _frame_lock:
        is_active = id in _screen_frames
    sse = SSEManager.get_instance()
    viewer_count = sse.get_subscriber_count(f"screen_{id}")
    return HTTPResponse.json({"active": is_active, "viewers": viewer_count})


def handle_stop_screen(
    request: HTTPRequest,
    db: Database,
    id: str = "",
) -> HTTPResponse:
    """POST /api/classroom/:id/screen/stop - Stop screen sharing"""
    user = get_user_from_request(request, db)
    if not user:
        return HTTPResponse.json({"error": "Unauthorized"}, 401)

    with _frame_lock:
        _screen_frames.pop(id, None)

    sse = SSEManager.get_instance()
    sse.publish(f"screen_{id}", "screen_stopped", {"message": "Screen sharing ended"})
    return HTTPResponse.json({"status": "stopped"})


def register_screen_routes(server, db: Database):
    server.add_route(
        "/api/classroom/:id/screen/frame",
        "POST",
        partial(handle_upload_frame, db=db),
    )
    server.add_route(
        "/api/classroom/:id/screen/stream",
        "GET",
        partial(handle_screen_stream, db=db),
    )
    server.add_route("/api/classroom/:id/screen/status", "GET", handle_screen_status)
    server.add_route(
        "/api/classroom/:id/screen/stop",
        "POST",
        partial(handle_stop_screen, db=db),
    )
