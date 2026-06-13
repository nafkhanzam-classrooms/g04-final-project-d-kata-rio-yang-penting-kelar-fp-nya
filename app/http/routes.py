from app.config.db.connection import Database
from app.controllers.screen_sharing.screen_controller import register_screen_routes
from app.routes.authentication.authentication_route import register_auth_routes
from app.routes.clasroom.classroom_route import register_classroom_routes
from app.routes.dashboard.dashboard_route import register_dashboard_routes
from app.routes.pptsharing.pptsharing_route import register_ppt_routes


def register_all_routes(server, db: Database | None = None) -> None:
    """Register all application routes with the HTTP server."""
    print("[ROUTES] Registering routes...")

    if db is None:
        db = Database.from_env()

    register_auth_routes(server, db)
    register_classroom_routes(server, db)
    register_screen_routes(server, db)
    register_ppt_routes(server)
    register_dashboard_routes(server, db)

    print("[ROUTES] All routes registered")
