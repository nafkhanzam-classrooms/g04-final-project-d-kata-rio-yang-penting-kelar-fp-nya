from functools import partial
from app.config.db.connection import Database
from app.controllers.authentication.auth_controller import (
    handle_login,
    handle_me,
    handle_register,
)
from app.http.http_server import HTTPServer


def register_auth_routes(server: HTTPServer, db: Database) -> None:
    """Register authentication routes with the HTTP server."""
    server.add_route(
        "/api/auth/register",
        "POST",
        partial(handle_register, db=db),
    )
    server.add_route(
        "/api/auth/login",
        "POST",
        partial(handle_login, db=db),
    )
    server.add_route(
        "/api/auth/me",
        "GET",
        partial(handle_me, db=db),
    )
