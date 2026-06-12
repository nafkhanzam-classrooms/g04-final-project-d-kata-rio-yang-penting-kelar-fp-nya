import json
import time
import hashlib
import hmac
import base64
import bcrypt
from functools import partial
from typing import Optional, Dict, Any
from app.config.db.connection import Database
from app.config.config import get_jwt_secret
from app.http.http_server import HTTPRequest, HTTPResponse
from app.models.user import UserRepository


def _create_jwt(payload: Dict[str, Any]) -> str:
    """Create a JWT token manually (HS256)."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload["iat"] = int(time.time())
    payload["exp"] = int(time.time()) + 86400  # 24 hours

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    h = b64url(json.dumps(header).encode())
    p = b64url(json.dumps(payload).encode())
    signature_input = f"{h}.{p}"
    sig = hmac.new(get_jwt_secret().encode(), signature_input.encode(), hashlib.sha256).digest()
    s = b64url(sig)
    return f"{h}.{p}.{s}"


def _decode_jwt(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify a JWT token."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        def b64url_decode(s: str) -> bytes:
            padding = 4 - len(s) % 4
            s += "=" * padding
            return base64.urlsafe_b64decode(s)

        h, p, s = parts
        signature_input = f"{h}.{p}"
        expected_sig = hmac.new(get_jwt_secret().encode(), signature_input.encode(), hashlib.sha256).digest()
        actual_sig = b64url_decode(s)

        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        payload = json.loads(b64url_decode(p))

        if payload.get("exp", 0) < time.time():
            return None

        return payload
    except Exception:
        return None


def get_user_from_request(
    request: HTTPRequest,
    db: Database,
) -> Optional[Dict[str, Any]]:
    """Extract and verify user from JWT in Authorization header."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    payload = _decode_jwt(token)
    if payload is None:
        return None
    user = db.fetch_one(
        """
        SELECT id, username, email, name AS display_name,
            0 AS total_points, 0 AS streak_days
        FROM users
        WHERE id = %s AND is_active = TRUE
        """,
        (payload.get("user_id"),),
    )
    return user


def handle_register(request: HTTPRequest, db: Database) -> HTTPResponse:
    """POST /api/auth/register"""
    try:
        data = request.json()
        username = data.get("username", "").strip()
        email = data.get("email", "").strip()
        password = data.get("password", "")
        display_name = data.get("display_name", username)

        if not username or not email or not password:
            return HTTPResponse.json({"error": "Username, email and password required"}, 400)

        if len(password) < 4:
            return HTTPResponse.json({"error": "Password must be at least 4 characters"}, 400)

        # Check duplicates
        existing = db.fetch_one(
            "SELECT id FROM users WHERE username = %s OR email = %s",
            (username, email),
        )
        if existing:
            return HTTPResponse.json({"error": "Username or email already taken"}, 409)

        # Hash password
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        user_id = UserRepository(db).create(
            username,
            display_name,
            email,
            password_hash,
        )

        token = _create_jwt({"user_id": user_id, "username": username})

        return HTTPResponse.json({
            "message": "Registration successful",
            "token": token,
            "user": {
                "id": user_id,
                "username": username,
                "email": email,
                "display_name": display_name,
            }
        }, 201)

    except Exception as e:
        print(f"[AUTH] Register error: {e}")
        return HTTPResponse.json({"error": str(e)}, 500)


def handle_login(request: HTTPRequest, db: Database) -> HTTPResponse:
    """POST /api/auth/login"""
    try:
        data = request.json()
        username = data.get("username", "").strip()
        password = data.get("password", "")

        if not username or not password:
            return HTTPResponse.json({"error": "Username and password required"}, 400)

        user = db.fetch_one(
            "SELECT * FROM users WHERE username = %s AND is_active = TRUE",
            (username,),
        )

        if not user:
            return HTTPResponse.json({"error": "Invalid credentials"}, 401)

        if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
            return HTTPResponse.json({"error": "Invalid credentials"}, 401)

        token = _create_jwt({"user_id": user["id"], "username": user["username"]})

        return HTTPResponse.json({
            "message": "Login successful",
            "token": token,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "display_name": user["name"],
                "total_points": 0,
                "streak_days": 0,
            }
        })

    except Exception as e:
        print(f"[AUTH] Login error: {e}")
        return HTTPResponse.json({"error": str(e)}, 500)


def handle_me(request: HTTPRequest, db: Database) -> HTTPResponse:
    """GET /api/auth/me"""
    user = get_user_from_request(request, db)
    if not user:
        return HTTPResponse.json({"error": "Unauthorized"}, 401)

    return HTTPResponse.json({"user": user})


def register_auth_routes(server, db: Database):
    """Register auth routes with the HTTP server."""
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
