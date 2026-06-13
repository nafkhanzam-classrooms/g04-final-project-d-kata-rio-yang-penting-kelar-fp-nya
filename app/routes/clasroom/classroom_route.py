from functools import partial
from app.config.db.connection import Database
from app.controllers.classroom.classroom_controller import (
    handle_classroom_news,
    handle_classroom_stream,
    handle_create_classroom,
    handle_get_classroom,
    handle_get_news,
    handle_join_classroom,
    handle_list_classrooms,
)
from app.http.http_server import HTTPServer


def register_classroom_routes(server: HTTPServer, db: Database) -> None:
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
