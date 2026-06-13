from functools import partial
from app.config.db.connection import Database
from app.controllers.dashboard.dashboard_controller import (
    handle_dashboard,
    handle_global_leaderboard,
)
from app.http.http_server import HTTPServer


def register_dashboard_routes(server: HTTPServer, db: Database) -> None:
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
