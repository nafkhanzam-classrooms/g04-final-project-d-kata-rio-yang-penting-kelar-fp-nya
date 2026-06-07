"""
CodEdu Server — Unified HTTP + WebSocket Server
=================================================
Pure Python server using select.epoll for concurrent I/O.

Features:
  - HTTP/1.1 request handling with keep-alive
  - Static file serving with security (directory traversal prevention)
  - REST API routing with path parameters
  - Native WebSocket protocol (RFC 6455) via app.http.websocket module
  - Session management: auth, reconnect, duplicate login kick, idle timeout
  - Heartbeat PING/PONG for connection health
  - Graceful malformed packet handling

Architecture:
  ┌─────────────────────────────────────────────┐
  │              CodEduServer                   │
  │  ┌──────────┐  ┌────────────┐  ┌─────────┐ │
  │  │  epoll   │──│ HTTP Router│──│ Static  │ │
  │  │  loop    │  │ (REST API) │  │ Files   │ │
  │  │          │  ├────────────┤  └─────────┘ │
  │  │          │──│ WebSocket  │              │
  │  │          │  │ Manager    │              │
  │  └──────────┘  ├────────────┤              │
  │                │  Session   │              │
  │                │  Store     │              │
  │                └────────────┘              │
  └─────────────────────────────────────────────┘

Author: CodEdu Infrastructure Team
"""

import json
import socket
import select
import time
import uuid
import logging
from pathlib import Path
from typing import Optional, Dict, Callable, List, Tuple, Any

from app.http.router import Route
from app.http.types import HTTPMethod
from app.http.multipart import MultipartFile
from app.http.websocket import (
    WebSocketHandshake,
    WebSocketFrame,
    WebSocketConnection,
    WSOpcode,
    WSCloseCode,
)

logger = logging.getLogger(__name__)

MAX_LISTEN_CLIENTS = 128
MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10 MB




class HTTPRequest:
    """Parsed HTTP request with multipart support."""

    def __init__(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        body: bytes = b"",
        query: str = "",
    ):
        self.method = method
        self.path = path
        self.headers = headers
        self.body = body
        self.query = query
        self.client_addr = None

        self.multipart_parsed = False
        self.multipart_form: Dict[str, str] = {}
        self.multipart_files: List[MultipartFile] = []

    @staticmethod
    def parse(raw_request: bytes) -> Optional["HTTPRequest"]:
        """Parse raw HTTP bytes into an HTTPRequest. Returns None on failure."""
        try:
            parts = raw_request.split(b"\r\n\r\n", 1)
            if len(parts) < 2:
                return None

            headers_bytes, body = parts

            header_block = headers_bytes.decode("utf-8", errors="ignore")
            lines = header_block.split("\r\n")

            if not lines:
                return None

            parts = lines[0].split()
            if len(parts) < 2:
                return None

            method = parts[0].upper()
            full_path = parts[1]

            if "?" in full_path:
                path, query = full_path.split("?", 1)
            else:
                path = full_path
                query = ""

            headers: Dict[str, str] = {}
            for line in lines[1:]:
                if ": " in line:
                    key, value = line.split(": ", 1)
                    headers[key.lower()] = value

            return HTTPRequest(method, path, headers, body, query)
        except Exception:
            return None

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    def _parse_multipart(self) -> None:
        """Parse multipart/form-data body."""
        if self.multipart_parsed:
            return

        boundary = self.boundary
        if not boundary:
            return

        try:
            boundary_bytes = ("--" + boundary).encode()
            parts = self.body.split(boundary_bytes)

            for part in parts:
                if not part.strip() or part.startswith(b"--"):
                    continue

                if part.startswith(b"\r\n"):
                    part = part[2:]

                header_end = part.find(b"\r\n\r\n")
                if header_end == -1:
                    continue

                headers_section = part[:header_end]
                data = part[header_end + 4:]
                data = data.rstrip(b"\r\n")

                header_text = headers_section.decode("utf-8", errors="ignore")
                filename = None
                field_name = None
                content_type = ""

                for line in header_text.split("\r\n"):
                    line_lower = line.lower()
                    if line_lower.startswith("content-disposition:"):
                        field_name, filename = self._extract_disposition_params(
                            line
                        )
                    elif line_lower.startswith("content-type:"):
                        content_type = line.split(":", 1)[1].strip()

                if not field_name:
                    continue

                if filename:
                    self.multipart_files.append(
                        MultipartFile(field_name, filename, content_type, data)
                    )
                else:
                    self.multipart_form[field_name] = data.decode(
                        "utf-8", errors="ignore"
                    )

            self.multipart_parsed = True

        except Exception as e:
            logger.warning(f"Multipart parse error: {e}")
            self.multipart_parsed = True

    def _extract_disposition_params(self, line: str) -> tuple:
        """Extract field_name and filename from Content-Disposition header."""
        field_name = None
        filename = None
        try:
            parts = line.split(";")
            for part in parts:
                part = part.strip()
                if part.lower().startswith("name="):
                    field_name = part[5:].strip('"').strip("'")
                elif part.lower().startswith("filename="):
                    filename = part[9:].strip('"').strip("'")
        except Exception:
            pass
        return field_name, filename

    def form(self) -> Dict[str, str]:
        self._parse_multipart()
        return self.multipart_form

    def files(self) -> List[MultipartFile]:
        self._parse_multipart()
        return self.multipart_files

    @property
    def content_type(self):
        return self.headers.get("content-type", "")

    @property
    def boundary(self) -> Optional[str]:
        content_type = self.content_type
        if "boundary=" not in content_type:
            return None
        try:
            boundary_part = content_type.split("boundary=", 1)[1]
            if boundary_part.startswith('"'):
                end_quote = boundary_part.find('"', 1)
                if end_quote != -1:
                    boundary = boundary_part[1:end_quote]
                else:
                    boundary = boundary_part[1:]
            else:
                boundary = boundary_part.split(";")[0].split()[0]
            return boundary.strip()
        except Exception:
            return None


class HTTPResponse:
    """HTTP response builder with common factory methods."""

    STATUS_CODES = {
        200: "OK",
        201: "Created",
        204: "No Content",
        301: "Moved Permanently",
        302: "Found",
        304: "Not Modified",
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        429: "Too Many Requests",
        500: "Internal Server Error",
        501: "Not Implemented",
    }

    CONTENT_TYPES = {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".txt": "text/plain; charset=utf-8",
        ".pdf": "application/pdf",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
    }

    def __init__(
        self,
        status: int = 200,
        body: bytes = b"",
        content_type: str = "text/plain; charset=utf-8",
    ):
        self.status = status
        self.reason = self.STATUS_CODES.get(status, "Unknown")
        self.body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.content_type = content_type
        self.headers: Dict[str, str] = {}

    def set_header(self, key: str, value: str) -> "HTTPResponse":
        self.headers[key] = value
        return self

    def set_headers(self, headers: Dict[str, str]) -> "HTTPResponse":
        self.headers.update(headers)
        return self

    def to_bytes(self) -> bytes:
        """Serialize response to HTTP wire format."""
        status_line = f"HTTP/1.1 {self.status} {self.reason}\r\n"

        header_lines = [
            f"Content-Length: {len(self.body)}",
            f"Content-Type: {self.content_type}",
            "Server: CodEdu/2.0",
            "X-Content-Type-Options: nosniff",
            "X-Frame-Options: DENY",
            "X-XSS-Protection: 1; mode=block",
        ]

        for key, value in self.headers.items():
            header_lines.append(f"{key}: {value}")

        if not any(
            k.lower() == "connection" for k in self.headers
        ):
            header_lines.append("Connection: close")

        headers_str = "\r\n".join(header_lines) + "\r\n\r\n"
        return status_line.encode("utf-8") + headers_str.encode("utf-8") + self.body

    @staticmethod
    def json(data: Any, status: int = 200) -> "HTTPResponse":
        body = json.dumps(data)
        return HTTPResponse(status, body.encode("utf-8"), "application/json")

    @staticmethod
    def text(text: str, status: int = 200) -> "HTTPResponse":
        return HTTPResponse(
            status, text.encode("utf-8"), "text/plain; charset=utf-8"
        )

    @staticmethod
    def html(html: str, status: int = 200) -> "HTTPResponse":
        return HTTPResponse(
            status, html.encode("utf-8"), "text/html; charset=utf-8"
        )

    @staticmethod
    def file(file_path: Path) -> "HTTPResponse":
        if not file_path.exists():
            return HTTPResponse(404, b"Not Found")
        content = file_path.read_bytes()
        content_type = HTTPResponse.CONTENT_TYPES.get(
            file_path.suffix, "application/octet-stream"
        )
        return HTTPResponse(200, content, content_type)

    @staticmethod
    def redirect(url: str, permanent: bool = False) -> "HTTPResponse":
        status = 301 if permanent else 302
        response = HTTPResponse(status, b"")
        response.set_header("Location", url)
        return response




class Session:
    """
    Represents a user session that can survive reconnects.
    Tied to a session_token (UUID), not a socket fd.
    """

    def __init__(self, username: str):
        self.token: str = uuid.uuid4().hex
        self.username: str = username
        self.fd: Optional[int] = None  # currently connected fd
        self.created_at: float = time.time()
        self.last_active: float = time.time()

    def attach(self, fd: int) -> None:
        """Attach this session to a socket fd."""
        self.fd = fd
        self.last_active = time.time()

    def detach(self) -> None:
        """Detach session from socket (disconnect without destroying session)."""
        self.fd = None

    def is_connected(self) -> bool:
        return self.fd is not None


class SessionStore:
    """
    Manages all active sessions.
    Keyed by session_token for reconnect lookup.
    Also maintains fd→token reverse mapping.
    """

    SESSION_TTL = 300  # 5 minutes to reconnect after disconnect

    def __init__(self) -> None:
        self.sessions: Dict[str, Session] = {}
        self.fd_to_token: Dict[int, str] = {}
        self.username_to_token: Dict[str, str] = {}

    def create(self, username: str) -> Session:
        """Create a new session for a user."""
        session = Session(username)
        self.sessions[session.token] = session
        self.username_to_token[username] = session.token
        return session

    def get_by_token(self, token: str) -> Optional[Session]:
        return self.sessions.get(token)

    def get_by_fd(self, fd: int) -> Optional[Session]:
        token = self.fd_to_token.get(fd)
        if token:
            return self.sessions.get(token)
        return None

    def get_by_username(self, username: str) -> Optional[Session]:
        token = self.username_to_token.get(username)
        if token:
            return self.sessions.get(token)
        return None

    def attach(self, token: str, fd: int) -> None:
        """Bind a session to a socket fd."""
        session = self.sessions.get(token)
        if session:
            session.attach(fd)
            self.fd_to_token[fd] = token

    def detach_fd(self, fd: int) -> Optional[Session]:
        """Unbind a socket fd from its session (keep session alive for reconnect)."""
        token = self.fd_to_token.pop(fd, None)
        if token:
            session = self.sessions.get(token)
            if session:
                session.detach()
                return session
        return None

    def destroy(self, token: str) -> None:
        """Fully remove a session."""
        session = self.sessions.pop(token, None)
        if session:
            if session.fd is not None:
                self.fd_to_token.pop(session.fd, None)
            self.username_to_token.pop(session.username, None)

    def cleanup_expired(self) -> List[str]:
        """Remove sessions that have been disconnected longer than TTL."""
        now = time.time()
        expired = []
        for token, session in list(self.sessions.items()):
            if not session.is_connected():
                if now - session.last_active > self.SESSION_TTL:
                    expired.append(token)
                    self.destroy(token)
        return expired




class CodEduServer:
    """
    Production-grade HTTP + WebSocket server using select.epoll.
    
    Handles:
      - HTTP requests → REST API + static files
      - WebSocket upgrades on /ws → real-time JSON messaging
      - Session management with reconnect support
      - Duplicate login detection and kicking
      - Heartbeat PING/PONG with idle timeout
      - Malformed packet handling without crashing
    """

    HEARTBEAT_INTERVAL = 30.0   # Send PING every 30s
    PONG_TIMEOUT = 10.0         # Drop connection if no PONG within 10s
    CLIENT_TIMEOUT = 60.0       # HTTP idle timeout
    SESSION_CLEANUP_INTERVAL = 60.0  # Check for expired sessions every 60s

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        static_dir: Optional[Path] = None,
    ):
        self.host = host
        self.port = port
        self.static_dir = static_dir.resolve() if static_dir else None

        self.running = False
        self.sock: Optional[socket.socket] = None

        self.poller = select.epoll()
        self.fd_to_socket: Dict[int, socket.socket] = {}
        self.socket_buffers: Dict[int, bytes] = {}
        self.client_last_active: Dict[int, float] = {}

        self.ws_connections: Dict[int, WebSocketConnection] = {}

        self.session_store = SessionStore()

        self.routes: List[Route] = []
        self.middleware: List[Callable] = []

        self._last_heartbeat = time.time()
        self._last_session_cleanup = time.time()

        self._ws_handlers: Dict[str, Callable] = {}
        self._register_default_ws_handlers()

    # ─── HTTP Routing ─────────────────────────────────────────

    def _convert_method(self, method: str) -> HTTPMethod:
        """Convert string HTTP method to enum."""
        mapping = {
            "GET": HTTPMethod.GET,
            "POST": HTTPMethod.POST,
            "PUT": HTTPMethod.PUT,
            "DELETE": HTTPMethod.DELETE,
            "OPTIONS": HTTPMethod.OPTIONS,
            "HEAD": HTTPMethod.HEAD,
        }
        return mapping.get(method.upper(), HTTPMethod.UNKNOWN)

    def route(
        self, path: str, methods: Optional[List[HTTPMethod]] = None
    ) -> Callable:
        """Decorator to register a route handler."""
        if methods is None:
            methods = [HTTPMethod.GET]

        def decorator(handler: Callable) -> Callable:
            for method in methods:
                r = Route(path, method, handler, is_pattern=":" in path)
                self.routes.append(r)
            return handler

        return decorator

    def add_route(self, path: str, method: str, handler: Callable) -> None:
        """Register a route handler by string method name."""
        m = self._convert_method(method)
        r = Route(path, m, handler, is_pattern=":" in path)
        self.routes.append(r)

    def get(self, path: str) -> Callable:
        return self.route(path, [HTTPMethod.GET])

    def post(self, path: str) -> Callable:
        return self.route(path, [HTTPMethod.POST])

    def put(self, path: str) -> Callable:
        return self.route(path, [HTTPMethod.PUT])

    def delete(self, path: str) -> Callable:
        return self.route(path, [HTTPMethod.DELETE])

    def use_middleware(self, middleware: Callable) -> None:
        self.middleware.append(middleware)

    def _apply_middleware(
        self, request: HTTPRequest
    ) -> Optional[HTTPResponse]:
        for mw in self.middleware:
            response = mw(request)
            if response is not None:
                return response
        return None

    def _find_handler(
        self, path: str, method: HTTPMethod
    ) -> Tuple[Optional[Callable], Dict[str, str]]:
        for route in self.routes:
            matches, params = route.matches(path, method)
            if matches:
                return route.handler, params
        return None, {}

    # ─── Static File Serving ──────────────────────────────────

    def serve_static(self, request: HTTPRequest) -> HTTPResponse:
        """Serve static files with directory traversal prevention."""
        if self.static_dir is None:
            return HTTPResponse(404, b"Static directory not configured")

        file_path = (self.static_dir / request.path.lstrip("/")).resolve()

        if not str(file_path).startswith(str(self.static_dir)):
            return HTTPResponse(403, b"Forbidden")

        if not file_path.exists():
            return HTTPResponse(404, b"Not Found")

        if file_path.is_dir():
            index_path = file_path / "index.html"
            if index_path.exists():
                file_path = index_path
            else:
                return HTTPResponse(404, b"Not Found")

        return HTTPResponse.file(file_path)

    def add_static_route(self, prefix: str = "/static") -> None:
        """Register a catch-all static file route."""

        def static_handler(request: HTTPRequest, **kwargs):
            return self.serve_static(request)

        self.add_route(f"{prefix}/:path", "GET", static_handler)

    # ─── HTTP Request Handling ────────────────────────────────

    def _handle_http_request(self, request: HTTPRequest) -> HTTPResponse:
        """Process an HTTP request through middleware and routing."""
        response = self._apply_middleware(request)
        if response is not None:
            return response

        handler, params = self._find_handler(
            request.path, self._convert_method(request.method)
        )

        if handler is None:
            return HTTPResponse(404, b"Not Found")

        try:
            response = handler(request, **params)
            if response is None:
                response = HTTPResponse(204, b"")
            return response
        except Exception as e:
            logger.error(f"Handler error: {e}", exc_info=True)
            return HTTPResponse(
                500, f"Internal Server Error".encode()
            )

    # ─── WebSocket Handlers ───────────────────────────────────

    def _register_default_ws_handlers(self) -> None:
        """Register built-in WebSocket message handlers."""
        self._ws_handlers["auth"] = self._handle_ws_auth
        self._ws_handlers["reconnect"] = self._handle_ws_reconnect
        self._ws_handlers["submit_code"] = self._handle_ws_submit
        self._ws_handlers["get_leaderboard"] = self._handle_ws_leaderboard
        self._ws_handlers["ping"] = self._handle_ws_ping

    def _handle_ws_auth(self, fd: int, data: dict) -> None:
        """Handle auth message: assign session to this connection."""
        username = data.get("username", "").strip()
        if not username or len(username) > 32:
            self._ws_send_json(fd, {
                "type": "error",
                "message": "Invalid username (1-32 characters required)",
            })
            return

        existing_session = self.session_store.get_by_username(username)
        if existing_session and existing_session.is_connected():
            old_fd = existing_session.fd
            self._ws_send_json(old_fd, {
                "type": "kick",
                "reason": "Duplicate login — another session connected",
            })
            self._ws_send_close(old_fd, WSCloseCode.POLICY_VIOLATION, "Duplicate login")
            self._cleanup_ws(old_fd)
            self.session_store.destroy(existing_session.token)

        from app.model.user_model import user_model

        user = user_model.get_or_create_user(username)

        session = self.session_store.create(username)
        session.attach(fd)
        self.session_store.fd_to_token[fd] = session.token

        ws_conn = self.ws_connections.get(fd)
        if ws_conn:
            ws_conn.username = username
            ws_conn.session_token = session.token
            ws_conn.authenticated = True

        self._ws_send_json(fd, {
            "type": "auth_ok",
            "session_token": session.token,
            "user": user.to_dict(),
        })

        logger.info(f"[WS] User '{username}' authenticated on fd {fd}")

    def _handle_ws_reconnect(self, fd: int, data: dict) -> None:
        """Handle reconnect: re-attach session to new connection."""
        token = data.get("session_token", "")
        if not token:
            self._ws_send_json(fd, {
                "type": "error",
                "message": "Missing session_token for reconnect",
            })
            return

        session = self.session_store.get_by_token(token)
        if not session:
            self._ws_send_json(fd, {
                "type": "error",
                "message": "Session expired or invalid. Please re-authenticate.",
                "code": "SESSION_EXPIRED",
            })
            return

        if session.is_connected() and session.fd != fd:
            old_fd = session.fd
            self._ws_send_json(old_fd, {
                "type": "kick",
                "reason": "Session resumed on another connection",
            })
            self._ws_send_close(old_fd, WSCloseCode.POLICY_VIOLATION, "Reconnected elsewhere")
            self._cleanup_ws(old_fd)

        session.attach(fd)
        self.session_store.fd_to_token[fd] = token

        ws_conn = self.ws_connections.get(fd)
        if ws_conn:
            ws_conn.username = session.username
            ws_conn.session_token = token
            ws_conn.authenticated = True

        from app.model.user_model import user_model
        user = user_model.get_user(session.username)

        self._ws_send_json(fd, {
            "type": "auth_ok",
            "session_token": token,
            "user": user.to_dict() if user else {},
            "reconnected": True,
        })

        logger.info(
            f"[WS] User '{session.username}' reconnected on fd {fd}"
        )

    def _handle_ws_submit(self, fd: int, data: dict) -> None:
        """Handle code submission via WebSocket."""
        ws_conn = self.ws_connections.get(fd)
        if not ws_conn or not ws_conn.authenticated:
            self._ws_send_json(fd, {
                "type": "error",
                "message": "Authentication required before submitting code",
            })
            return

        code = data.get("code", "")
        problem_id = data.get("problem_id", "")

        if not code or not problem_id:
            self._ws_send_json(fd, {
                "type": "error",
                "message": "Missing 'code' or 'problem_id'",
            })
            return

        from app.controllers.user_controller import UserController

        result = UserController.submit_code_ws(
            code, problem_id, ws_conn.username or "user1"
        )

        self._ws_send_json(fd, {
            "type": "submission_result",
            **result,
        })

        if result.get("status") == "Accepted" and result.get("user_stats"):
            stats = result["user_stats"]
            self._ws_send_json(fd, {
                "type": "streak_update",
                "current_streak": stats.get("current_streak", 0),
                "streak_bonus": stats.get("streak_bonus", False),
                "points_earned": stats.get("points_earned", 0),
                "total_points": stats.get("total_points", 0),
                "rank": stats.get("rank", 0),
                "multiplier": stats.get("multiplier", 1.0),
            })

    def _handle_ws_leaderboard(self, fd: int, data: dict) -> None:
        """Handle leaderboard request."""
        from app.model.user_model import user_model

        leaderboard = user_model.get_leaderboard()
        self._ws_send_json(fd, {
            "type": "leaderboard",
            "rankings": leaderboard,
        })

    def _handle_ws_ping(self, fd: int, data: dict) -> None:
        """Handle application-level ping (not WS protocol ping)."""
        self._ws_send_json(fd, {"type": "pong", "ts": time.time()})

    # ─── WebSocket I/O Helpers ────────────────────────────────

    def _ws_send_json(self, fd: int, data: dict) -> None:
        """Send a JSON payload over WebSocket to a specific fd."""
        sock = self.fd_to_socket.get(fd)
        if not sock:
            return
        try:
            payload = json.dumps(data).encode("utf-8")
            frame = WebSocketFrame.build(payload, WSOpcode.TEXT)
            sock.sendall(frame)
        except (BrokenPipeError, OSError, ConnectionResetError) as e:
            logger.warning(f"[WS] Send failed to fd {fd}: {e}")

    def _ws_send_close(
        self,
        fd: int,
        code: WSCloseCode = WSCloseCode.NORMAL,
        reason: str = "",
    ) -> None:
        """Send a WebSocket CLOSE frame."""
        sock = self.fd_to_socket.get(fd)
        if not sock:
            return
        try:
            frame = WebSocketFrame.build_close(code, reason)
            sock.sendall(frame)
        except (BrokenPipeError, OSError):
            pass

    def _ws_broadcast(self, data: dict, exclude_fd: Optional[int] = None) -> None:
        """Broadcast JSON to all authenticated WebSocket connections."""
        for fd, ws_conn in self.ws_connections.items():
            if fd == exclude_fd:
                continue
            if ws_conn.authenticated:
                self._ws_send_json(fd, data)

    # ─── Socket Setup & Accept ────────────────────────────────

    def _setup_socket(self) -> None:
        """Create, bind, and listen on server socket."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.setblocking(False)
        self.sock.listen(MAX_LISTEN_CLIENTS)

        self.poller.register(self.sock, select.EPOLLIN)
        self.fd_to_socket[self.sock.fileno()] = self.sock

    def _accept_client(self) -> None:
        """Accept a new incoming TCP connection."""
        if self.sock is None:
            return

        try:
            client_sock, client_addr = self.sock.accept()
            client_sock.setblocking(False)

            fd = client_sock.fileno()
            self.poller.register(client_sock, select.EPOLLIN)
            self.fd_to_socket[fd] = client_sock
            self.socket_buffers[fd] = b""
            self.client_last_active[fd] = time.time()
        except BlockingIOError:
            pass

    # ─── Request Completeness Check ───────────────────────────

    def _request_complete(self, buffer: bytes) -> bool:
        """Check if the buffer contains a complete HTTP request."""
        if b"\r\n\r\n" not in buffer:
            return False

        header_end = buffer.find(b"\r\n\r\n")
        headers = buffer[:header_end].decode("utf-8", errors="ignore")
        body = buffer[header_end + 4:]
        content_len = 0

        for line in headers.split("\r\n"):
            if line.lower().startswith("content-length:"):
                try:
                    content_len = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
                break

        return len(body) >= content_len

    # ─── Data Reading & Dispatch ──────────────────────────────

    def _read_from_client(self, client_sock: socket.socket) -> None:
        """Read data from a client socket and dispatch."""
        fd = client_sock.fileno()
        self.client_last_active[fd] = time.time()

        try:
            data = client_sock.recv(8192)
            if not data:
                self._cleanup_client(client_sock)
                return

            current_buffer = self.socket_buffers.get(fd, b"")
            if len(current_buffer) + len(data) > MAX_REQUEST_SIZE:
                logger.warning(f"[SERVER] Request too large from fd {fd}")
                self._cleanup_client(client_sock)
                return

            if fd in self.ws_connections:
                self._handle_ws_data(fd, data)
                return

            self.socket_buffers[fd] = current_buffer + data

            if self._request_complete(self.socket_buffers[fd]):
                self._process_http_request(client_sock)

        except (OSError, ConnectionResetError):
            self._cleanup_client(client_sock)

    # ─── HTTP Processing ──────────────────────────────────────

    def _process_http_request(self, client_sock: socket.socket) -> None:
        """Parse and handle a complete HTTP request."""
        fd = client_sock.fileno()
        request_data = self.socket_buffers.get(fd, b"")

        request = HTTPRequest.parse(request_data)
        keep_alive = False

        if request is None:
            response = HTTPResponse(400, b"Bad Request - Malformed Packet")
        else:
            request.client_addr = client_sock.getpeername()

            if self._is_ws_upgrade(request):
                self._handle_ws_upgrade(fd, request)
                self.socket_buffers[fd] = b""
                return

            conn_header = request.headers.get("connection", "").lower()
            if conn_header == "keep-alive":
                keep_alive = True

            response = self._handle_http_request(request)

        if keep_alive:
            response.set_header("Connection", "keep-alive")
        else:
            response.set_header("Connection", "close")

        try:
            client_sock.sendall(response.to_bytes())
        except (BrokenPipeError, OSError):
            keep_alive = False

        if keep_alive:
            self.socket_buffers[fd] = b""
            self.client_last_active[fd] = time.time()
        else:
            self._cleanup_client(client_sock)

    # ─── WebSocket Upgrade ────────────────────────────────────

    def _is_ws_upgrade(self, request: HTTPRequest) -> bool:
        """Check if this HTTP request is a WebSocket upgrade."""
        return (
            request.path == "/ws"
            and WebSocketHandshake.is_websocket_upgrade(request.headers)
        )

    def _handle_ws_upgrade(self, fd: int, request: HTTPRequest) -> None:
        """Perform WebSocket handshake and register the connection."""
        ws_key = request.headers.get("sec-websocket-key", "")
        if not ws_key:
            sock = self.fd_to_socket.get(fd)
            if sock:
                reject = WebSocketHandshake.build_reject_response(
                    400, "Missing Sec-WebSocket-Key"
                )
                try:
                    sock.sendall(reject)
                except OSError:
                    pass
            return

        sock = self.fd_to_socket.get(fd)
        if not sock:
            return

        accept_response = WebSocketHandshake.build_accept_response(ws_key)
        try:
            sock.sendall(accept_response)
        except OSError:
            return

        ws_conn = WebSocketConnection(fd)
        ws_conn.handshake_complete = True
        ws_conn.last_pong_time = time.time()
        self.ws_connections[fd] = ws_conn

        self.socket_buffers[fd] = b""

        logger.info(f"[WS] WebSocket handshake complete for fd {fd}")

    # ─── WebSocket Data Handling ──────────────────────────────

    def _handle_ws_data(self, fd: int, data: bytes) -> None:
        """Process incoming WebSocket frame data."""
        ws_conn = self.ws_connections.get(fd)
        if not ws_conn:
            return

        try:
            ws_conn.feed(data)
        except ValueError as e:
            logger.warning(f"[WS] Buffer overflow on fd {fd}: {e}")
            self._ws_send_close(fd, WSCloseCode.MESSAGE_TOO_BIG, "Message too large")
            self._cleanup_ws(fd)
            return

        try:
            messages = ws_conn.parse_frames()
        except ValueError as e:
            logger.warning(f"[WS] Protocol error on fd {fd}: {e}")
            self._ws_send_close(fd, WSCloseCode.PROTOCOL_ERROR, str(e)[:100])
            self._cleanup_ws(fd)
            return

        for msg in messages:
            opcode = msg["opcode"]
            payload = msg["payload"]

            if opcode == WSOpcode.CLOSE:
                self._ws_send_close(fd, WSCloseCode.NORMAL)
                self._cleanup_ws(fd)
                return

            elif opcode == WSOpcode.PING:
                pong_frame = WebSocketFrame.build_pong(payload)
                sock = self.fd_to_socket.get(fd)
                if sock:
                    try:
                        sock.sendall(pong_frame)
                    except OSError:
                        pass

            elif opcode == WSOpcode.PONG:
                ws_conn.last_pong_time = time.time()
                ws_conn.ping_pending = False

            elif opcode == WSOpcode.TEXT:
                self._dispatch_ws_message(fd, payload)

    def _dispatch_ws_message(self, fd: int, payload: bytes) -> None:
        """Parse JSON and dispatch to the appropriate handler."""
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            self._ws_send_json(fd, {
                "type": "error",
                "message": "Invalid UTF-8 payload",
            })
            return

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            self._ws_send_json(fd, {
                "type": "error",
                "message": "Malformed JSON — could not parse message",
            })
            return

        if not isinstance(data, dict):
            self._ws_send_json(fd, {
                "type": "error",
                "message": "Expected JSON object, got " + type(data).__name__,
            })
            return

        msg_type = data.get("type", "")
        if not msg_type:
            self._ws_send_json(fd, {
                "type": "error",
                "message": "Missing 'type' field in message",
            })
            return

        handler = self._ws_handlers.get(msg_type)
        if handler:
            try:
                handler(fd, data)
            except Exception as e:
                logger.error(
                    f"[WS] Handler error for '{msg_type}': {e}",
                    exc_info=True,
                )
                self._ws_send_json(fd, {
                    "type": "error",
                    "message": "Server error processing your request",
                })
        else:
            self._ws_send_json(fd, {
                "type": "error",
                "message": f"Unknown message type: '{msg_type}'",
            })

    # ─── Heartbeat & Timeout ──────────────────────────────────

    def _run_heartbeat(self) -> None:
        """Send PING to all WebSocket connections and check for PONG timeout."""
        now = time.time()
        if now - self._last_heartbeat < self.HEARTBEAT_INTERVAL:
            return
        self._last_heartbeat = now

        for fd in list(self.ws_connections.keys()):
            ws_conn = self.ws_connections.get(fd)
            if not ws_conn:
                continue

            if ws_conn.ping_pending:
                if now - ws_conn.last_pong_time > self.PONG_TIMEOUT + self.HEARTBEAT_INTERVAL:
                    logger.info(f"[WS] Dropping idle connection fd {fd} (no PONG)")
                    self._ws_send_close(fd, WSCloseCode.GOING_AWAY, "Idle timeout")
                    self._cleanup_ws(fd)
                    continue

            sock = self.fd_to_socket.get(fd)
            if sock:
                try:
                    ping_frame = WebSocketFrame.build_ping(b"heartbeat")
                    sock.sendall(ping_frame)
                    ws_conn.ping_pending = True
                except (OSError, BrokenPipeError):
                    self._cleanup_ws(fd)

    def _check_http_timeouts(self) -> None:
        """Drop idle HTTP connections (not WebSocket)."""
        now = time.time()
        for fd in list(self.client_last_active.keys()):
            if fd in self.ws_connections:
                continue

            if now - self.client_last_active[fd] > self.CLIENT_TIMEOUT:
                sock = self.fd_to_socket.get(fd)
                if sock:
                    self._cleanup_client(sock)

    def _run_session_cleanup(self) -> None:
        """Periodically clean up expired disconnected sessions."""
        now = time.time()
        if now - self._last_session_cleanup < self.SESSION_CLEANUP_INTERVAL:
            return
        self._last_session_cleanup = now

        expired = self.session_store.cleanup_expired()
        if expired:
            logger.info(f"[SESSION] Cleaned up {len(expired)} expired sessions")

    # ─── Cleanup ──────────────────────────────────────────────

    def _cleanup_ws(self, fd: int) -> None:
        """Clean up a WebSocket connection (detach session, remove ws_conn)."""
        self.ws_connections.pop(fd, None)
        self.session_store.detach_fd(fd)

        sock = self.fd_to_socket.get(fd)
        if sock:
            self._cleanup_client(sock)

    def _cleanup_client(self, client_sock: socket.socket) -> None:
        """Clean up a client socket entirely."""
        try:
            fd = client_sock.fileno()
        except OSError:
            return

        if fd in self.ws_connections:
            self.ws_connections.pop(fd, None)
            self.session_store.detach_fd(fd)

        try:
            self.poller.unregister(fd)
        except (OSError, ValueError):
            pass

        self.fd_to_socket.pop(fd, None)
        self.socket_buffers.pop(fd, None)
        self.client_last_active.pop(fd, None)

        try:
            client_sock.close()
        except Exception:
            pass

    # ─── Health Check Endpoint ────────────────────────────────

    def _register_health_endpoint(self) -> None:
        """Register /health for Docker health checks."""

        def health_handler(request: HTTPRequest, **kwargs):
            return HTTPResponse.json({
                "status": "healthy",
                "active_ws": len(self.ws_connections),
                "active_sessions": len(self.session_store.sessions),
                "uptime": time.time() - self._start_time,
            })

        self.add_route("/health", "GET", health_handler)

    # ─── Main Event Loop ─────────────────────────────────────

    def run(self) -> None:
        """Start the server event loop."""
        try:
            self._setup_socket()
            self._register_health_endpoint()
            self.running = True
            self._start_time = time.time()

            logger.info(
                f"[CODEDU] Server listening on {self.host}:{self.port}"
            )
            print(
                f"[CODEDU] Server listening on {self.host}:{self.port}"
            )

            while self.running:
                try:
                    events = self.poller.poll(1.0)

                    for fd, event in events:
                        sock = self.fd_to_socket.get(fd)
                        if sock is None:
                            continue

                        if sock == self.sock:
                            self._accept_client()
                        elif event & select.EPOLLIN:
                            self._read_from_client(sock)
                        elif event & (select.EPOLLHUP | select.EPOLLERR):
                            self._cleanup_client(sock)

                    self._run_heartbeat()
                    self._check_http_timeouts()
                    self._run_session_cleanup()

                except KeyboardInterrupt:
                    print("\n[CODEDU] Shutdown requested")
                    break
                except Exception as e:
                    logger.error(f"[CODEDU] Event loop error: {e}", exc_info=True)

        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Graceful shutdown: close all connections and the server socket."""
        self.running = False

        for fd in list(self.ws_connections.keys()):
            self._ws_send_close(fd, WSCloseCode.GOING_AWAY, "Server shutting down")

        for sock in list(self.fd_to_socket.values()):
            try:
                self.poller.unregister(sock.fileno())
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass

        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass

        logger.info("[CODEDU] Server shutdown complete")
        print("[CODEDU] Server shutdown complete")




def cors_middleware(request: HTTPRequest) -> Optional[HTTPResponse]:
    """CORS middleware — allows all origins for development."""
    if request.method == "OPTIONS":
        response = HTTPResponse(204, b"")
        response.set_header("Access-Control-Allow-Origin", "*")
        response.set_header(
            "Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS"
        )
        response.set_header(
            "Access-Control-Allow-Headers", "Content-Type, Authorization"
        )
        return response
    return None


def logging_middleware(request: HTTPRequest) -> Optional[HTTPResponse]:
    """Log every incoming HTTP request."""
    logger.info(f"[REQUEST] {request.method} {request.path}")
    return None




def parse_query_params(query_string: str) -> Dict[str, str]:
    params: Dict[str, str] = {}
    if query_string:
        for pair in query_string.split("&"):
            if "=" in pair:
                key, value = pair.split("=", 1)
                params[key] = value
    return params


def get_content_type(file_extension: str) -> str:
    return HTTPResponse.CONTENT_TYPES.get(
        file_extension.lower(), "application/octet-stream"
    )
