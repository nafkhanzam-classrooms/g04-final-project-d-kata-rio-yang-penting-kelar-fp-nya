# permission checking middleware to place and use along with HTTPServer routes
# usage examples
    # from app.db.connection import Database
    # from app.models.user import UserRepository
    # from app.middleware.permissions import require_permission
    #
    # db   = Database.from_env()
    # repo = UserRepository(db)
    #
    # @require_permission(repo, "ppt.control")
    # def handle_next_slide(request: HTTPRequest) -> HTTPResponse:
    #     ...
    #

# for now the decorator handler expects from the users header to have a custom header
# of X-User-Id header (temporaly) to have some kind of check on user role and ID
# if the project have time to implement a basic cookie-session based, the X-User-Id will get replaced after

import functools
from typing import Callable

from app.http.http_server import HTTPRequest, HTTPResponse
from app.models.user import UserRepository


def _get_user_id(request: HTTPRequest) -> int | None:
    # for now extracting the user ID from the request through the X-User-Id custom header
    header_val = request.headers.get("x-user-id")
    if header_val is None:
        return None
    try:
        return int(header_val)
    except ValueError:
        return None


def require_permission(repo: UserRepository, permission_code: str) -> Callable:
    # decorator factory that wraps a route handler so it only runs if the requesting user
    # has the given permission
    # returns 401 status code if no user ID is present within the HTTP request
    # 403 if the user ID do not have the minimum required permission

    def decorator(handler: Callable[[HTTPRequest], HTTPResponse]) -> Callable:
        @functools.wraps(handler)
        def wrapper(request: HTTPRequest, *args, **kwargs) -> HTTPResponse:
            user_id = _get_user_id(request)
            if user_id is None:
                return HTTPResponse.json({"error": "Unauthorized"}, 401)

            if not repo.has_permission(user_id, permission_code):
                return HTTPResponse.json(
                    {"error": f"Forbidden: missing permission '{permission_code}'"}, 403
                )

            return handler(request, *args, **kwargs)

        return wrapper

    return decorator


def require_role(repo: UserRepository, role_name: str) -> Callable:
    # the same as require_permission but strictly to role only

    def decorator(handler: Callable[[HTTPRequest], HTTPResponse]) -> Callable:
        @functools.wraps(handler)
        def wrapper(request: HTTPRequest, *args, **kwargs) -> HTTPResponse:
            user_id = _get_user_id(request)
            if user_id is None:
                return HTTPResponse.json({"error": "Unauthorized"}, 401)

            if not repo.has_role(user_id, role_name):
                return HTTPResponse.json(
                    {"error": f"Forbidden: requires role '{role_name}'"}, 403
                )

            return handler(request, *args, **kwargs)

        return wrapper

    return decorator
