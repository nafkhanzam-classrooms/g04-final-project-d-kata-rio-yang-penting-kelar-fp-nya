from app.config.db.connection import Database
from app.controllers.authentication.auth_controller import register_auth_routes
from app.controllers.classroom.classroom_controller import register_classroom_routes
from app.controllers.dashboard.dashboard_controller import register_dashboard_routes
from app.controllers.screen_sharing.screen_controller import register_screen_routes
from app.routes.pptsharing.pptsharing_route import register_ppt_routes


def register_all_routes(server):
    """Register all application routes with the HTTP server."""
    print("[ROUTES] Registering routes...")

    db = Database.from_env()

    register_auth_routes(server, db)
    register_classroom_routes(server, db)
    register_screen_routes(server, db)
    register_ppt_routes(server)
    register_dashboard_routes(server, db)

    print("[ROUTES] All routes registered")
