import json
import socket
import select
import time
from pathlib import Path
from typing import Optional, Dict, Callable, List, Tuple, Any
from enum import Enum

MAX_LISTEN_CLIENTS = 10

class HTTPMethod(Enum):
    # HTTP Methods as Enumeration (Lookup Table)
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    OPTIONS = "OPTIONS"
    HEAD = "HEAD"


class HTTPRequest:
    def __init__(self, method: str, path: str, headers: Dict[str, str], body: str = "", query: str = ""):
        self.method = method
        self.path = path
        self.headers = headers
        self.body = body
        self.query = query
        self.client_addr = None
    
    # static method to parse incoming HTTP request and returns an instance of HTTP request so it can be reusable
    # if in the middle of parsing an error occurs, the method will returns None
    @staticmethod
    def parse(raw_request: str) -> Optional["HTTPRequest"]:
        try:
            header_block, _, body = raw_request.partition('\r\n\r\n')

            print(header_block)
            print(_ + "\n\n")
            print(body)
            lines = header_block.split('\r\n')
            
            if not lines:
                return None
            
            # Parse request line
            parts = lines[0].split()
            if len(parts) < 2:
                return None
            
            method = parts[0].upper()
            full_path = parts[1]
            
            # Split path and query
            if "?" in full_path:
                path, query = full_path.split("?", 1)
            else:
                path = full_path
                query = ""
            
            # Parse headers
            headers = {}
            for line in lines[1:]:
                if ": " in line:
                    key, value = line.split(": ", 1)
                    headers[key.lower()] = value
            
            return HTTPRequest(method, path, headers, body, query)
        except Exception:
            return None


class HTTPResponse:
    
    # Common status codes look-up table
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
        500: "Internal Server Error",
        501: "Not Implemented",
    }
    
    # common types that commonly used in HTTP requests for displaying a web page
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
        ".txt": "text/plain; charset=utf-8",
        ".pdf": "application/pdf",
    }
    
    # defaulting the http status code to 200 and its content_type to text/plain
    def __init__(
        self,
        status: int = 200,
        body: bytes = b"",
        content_type: str = "text/plain; charset=utf-8"
    ):
        self.status = status
        self.reason = self.STATUS_CODES.get(status, "Unknown")
        self.body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.content_type = content_type
        self.headers: Dict[str, str] = {}
        self.headers_sent = False
    
    # add and sets the http response header value
    def set_header(self, key: str, value: str) -> "HTTPResponse":
        self.headers[key] = value
        return self
    
    # set multiple headers at once
    def set_headers(self, headers: Dict[str, str]) -> "HTTPResponse":
        self.headers.update(headers)
        return self
    
    # convert the http response to bytes to allow socket programming to transmit the response to the client
    def to_bytes(self) -> bytes:
        """Convert response to HTTP bytes."""
        status_line = f"HTTP/1.1 {self.status} {self.reason}\r\n"
        
        header_lines = [
            f"Content-Length: {len(self.body)}",
            f"Content-Type: {self.content_type}",
            "Connection: close",
        ]
        
        # Add custom headers
        for key, value in self.headers.items():
            header_lines.append(f"{key}: {value}")
        
        headers_str = "\r\n".join(header_lines) + "\r\n\r\n"
        return status_line.encode("utf-8") + headers_str.encode("utf-8") + self.body
    
    # make http response as a JSON for its content_type
    @staticmethod
    def json(data: Any, status: int = 200) -> "HTTPResponse":
        body = json.dumps(data)
        return HTTPResponse(status, body.encode("utf-8"), "application/json")
    
    # make http response as a regular text for its content_type
    @staticmethod
    def text(text: str, status: int = 200) -> "HTTPResponse":
        return HTTPResponse(status, text.encode("utf-8"), "text/plain; charset=utf-8")
    
    # make http response as an HTML page for its content_type
    @staticmethod
    def html(html: str, status: int = 200) -> "HTTPResponse":
        return HTTPResponse(status, html.encode("utf-8"), "text/html; charset=utf-8")
    
    # make http response as a file and set its content_type to octet-stream
    @staticmethod
    def file(file_path: Path) -> "HTTPResponse":
        if not file_path.exists():
            return HTTPResponse(404, b"Not Found")
        
        content = file_path.read_bytes()
        content_type = HTTPResponse.CONTENT_TYPES.get(
            file_path.suffix,
            "application/octet-stream"
        )
        return HTTPResponse(200, content, content_type)


    # make http response a redirect by sending 3xx to the client
    @staticmethod
    def redirect(url: str, permanent: bool = False) -> "HTTPResponse":
        """Create redirect response."""
        status = 301 if permanent else 302
        response = HTTPResponse(status, b"")
        response.set_header("Location", url)
        return response


class Route:
    # generalizing custom HTTP route so it can be reused in different scenarios
    
    def __init__(
        self,
        path: str,
        method: str,
        handler: Callable,
        is_pattern: bool = False
    ):
        self.path = path
        self.method = method
        self.handler = handler
        self.is_pattern = is_pattern
    
    # check if the path matches the route's own path (excluding anchor and get parameters), doing simple pattern matching (no regex)
    def matches(self, path: str, method: str) -> Tuple[bool, Dict[str, str]]:
        if self.method.upper() != method.upper():
            return False, {}
        
        if not self.is_pattern:
            return self.path == path, {}
        
        # Simple pattern matching: /users/:id -> /users/123
        pattern_parts = self.path.split('/')
        path_parts = path.split('/')
        
        if len(pattern_parts) != len(path_parts):
            return False, {}
        
        params = {}
        for pattern_part, path_part in zip(pattern_parts, path_parts):
            if pattern_part.startswith(':'):
                params[pattern_part[1:]] = path_part
            elif pattern_part != path_part:
                return False, {}
        
        return True, params


class HTTPServer:
    # Using socket.socket and select.poll to handle multiple client connection
    # provided a way to basic routing handling, supporting multiple http methods defined in the HTTPMethod enum
    def __init__(self, host: str = "0.0.0.0", port: int = 8000, static_dir: Optional[Path] = None):
        """Initialize server."""
        self.host = host
        self.port = port
        self.static_dir = static_dir.resolve() if static_dir else None
        
        # Server state
        self.running = False
        self.sock: Optional[socket.socket] = None
        
        # Socket management
        self.poller = select.poll()
        self.fd_to_socket: Dict[int, socket.socket] = {}
        self.socket_buffers: Dict[int, bytes] = {}
        
        # Routing
        self.routes: List[Route] = []
        
        # Middleware
        self.middleware: List[Callable] = []
    
    
    # decorator function to register a route to the HTTP server for multiple methods for the same path
    def route(self, path: str, methods: Optional[List[str]] = None) -> Callable:
        if methods is None:
            methods = ["GET"]
        
        def decorator(handler: Callable) -> Callable:
            for method in methods:
                route = Route(path, method, handler, is_pattern=":" in path)
                self.routes.append(route)
            return handler
        
        return decorator
    
    # add a route handler manually by specifying the method and the path individually
    def add_route(self, path: str, method: str, handler: Callable) -> None:
        route = Route(path, method, handler, is_pattern=":" in path)
        self.routes.append(route)
    
    # decorator function to automatically adds a route by calling its designated method and the path string
    def get(self, path: str) -> Callable:
        return self.route(path, ["GET"])
    
    def post(self, path: str) -> Callable:
        return self.route(path, ["POST"])
    
    def put(self, path: str) -> Callable:
        return self.route(path, ["PUT"])
    
    def delete(self, path: str) -> Callable:
        return self.route(path, ["DELETE"])
    
    
    # middleware for the route handler
    # registering a middleware to this route
    def use_middleware(self, middleware: Callable) -> None:
        self.middleware.append(middleware)
    
    def _apply_middleware(self, request: HTTPRequest) -> Optional[HTTPResponse]:
        for mw in self.middleware:
            response = mw(request)
            if response is not None:
                return response
        return None
    
    # request handling functions
    # function that starts with _ indicates an internal function (private) defined to help the main callable (public) functions


    # internal function to find the handler for a specific path and method, 
    # returns the callable object for the handler and the params included in the path, otherwise just an empty tuple
    def _find_handler(self, path: str, method: str) -> Tuple[Optional[Callable], Dict[str, str]]:
        for route in self.routes:
            matches, params = route.matches(path, method)
            if matches:
                return route.handler, params
        return None, {}
    
    # process a request and generate a response based on the middleware (handler) the path has
    # if the handler is unknown, 404 will be returned
    # if the handler response is None, 204 will be returned
    # if there are errors in the function, 500 will be returned
    def _handle_request_impl(self, request: HTTPRequest) -> HTTPResponse:
        """Process request and generate response."""
        # Apply middleware
        response = self._apply_middleware(request)
        if response is not None:
            return response
        
        # Find and call handler
        handler, params = self._find_handler(request.path, request.method)
        
        if handler is None:
            return HTTPResponse(404, b"Not Found")
        
        try:
            # Call handler with request and params
            response = handler(request, **params)
            if response is None:
                response = HTTPResponse(204, b"")
            return response
        except Exception as e:
            print(f"[ERROR] Handler error: {e}")
            return HTTPResponse(500, f"Internal Server Error: {str(e)}".encode())
    
    # public function for handling request, providing the parameter is the HTTPRequest object
    def handle_request(self, request: HTTPRequest) -> HTTPResponse:
        """
        Override this method to customize request handling.
        Default implementation uses routing and middleware.
        """
        return self._handle_request_impl(request)
    
    # socket management for communicating using TCP for the HTTP
    # private function to setup the socket using TCP, reuseaddr to prevent port usage blocked, binding the server's address and port and listening
    # handling multiple client using poller.register for now using the select.poll
    def _setup_socket(self) -> None:
        """Setup server socket."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.setblocking(False)
        self.sock.listen(max(MAX_LISTEN_CLIENTS, 5))
        
        self.poller.register(self.sock, select.POLLIN)
        self.fd_to_socket[self.sock.fileno()] = self.sock
    
    # accept incoming client connection and adding it to the cliend fd's
    def _accept_client(self) -> None:
        """Accept incoming client connection."""
        try:
            client_sock, client_addr = self.sock.accept()
            client_sock.setblocking(False)
            
            fd = client_sock.fileno()
            self.poller.register(client_sock, select.POLLIN)
            self.fd_to_socket[fd] = client_sock
            self.socket_buffers[fd] = b""
        except BlockingIOError:
            pass
    
    # read data from client using socket_buffers buffer
    def _read_from_client(self, client_sock: socket.socket) -> None:
        fd = client_sock.fileno()
        
        try:
            data = client_sock.recv(4096)
            if not data:
                self._cleanup_client(client_sock)
                return
            
            # Accumulate data in buffer
            self.socket_buffers[fd] += data
            
            # Check if we have complete request (ends with \r\n\r\n)
            if b'\r\n\r\n' in self.socket_buffers[fd]:
                self._process_client_request(client_sock)
        except (OSError, ConnectionResetError):
            self._cleanup_client(client_sock)
    
    # parsing request from client and doing cleanup process after done (no persistent connection)
    def _process_client_request(self, client_sock: socket.socket) -> None:
        fd = client_sock.fileno()
        request_data = self.socket_buffers[fd].decode('utf-8', errors='ignore')
        
        # Parse request
        request = HTTPRequest.parse(request_data)
        if request is None:
            response = HTTPResponse(400, b"Bad Request")
        else:
            request.client_addr = client_sock.getpeername()
            response = self.handle_request(request)
        
        # Send response
        try:
            client_sock.sendall(response.to_bytes())
        except (BrokenPipeError, OSError):
            pass
        finally:
            self._cleanup_client(client_sock)
    
    # cleanup a client socket and deletes the entry on the fd's list of client sockets
    def _cleanup_client(self, client_sock: socket.socket) -> None:
        fd = client_sock.fileno()
        
        try:
            self.poller.unregister(fd)
        except (OSError, ValueError):
            pass
        
        self.fd_to_socket.pop(fd, None)
        self.socket_buffers.pop(fd, None)
        
        try:
            client_sock.close()
        except:
            pass
    
    
    # serve static files (css, js, etc.)
    def serve_static(self, request: HTTPRequest) -> HTTPResponse:
        if self.static_dir is None:
            return HTTPResponse(404, b"Static directory not configured")
        
        file_path = (self.static_dir / request.path.lstrip('/')).resolve()
        
        # Security: prevent directory traversal
        if not str(file_path).startswith(str(self.static_dir)):
            return HTTPResponse(403, b"Forbidden")
        
        if not file_path.exists():
            return HTTPResponse(404, b"Not Found")
        
        if file_path.is_dir():
            # Try to serve index.html
            index_path = file_path / "index.html"
            if index_path.exists():
                file_path = index_path
            else:
                return HTTPResponse(404, b"Not Found")
        
        return HTTPResponse.file(file_path)
    
    # function to add static routes (possible static routes)
    def add_static_route(self, prefix: str = "/static") -> None:
        def static_handler(request: HTTPRequest):
            return self.serve_static(request)
        
        # Register as catch-all pattern for this prefix
        self.add_route(f"{prefix}/<path>", "GET", static_handler)
    
    
    # main driver for the HTTP server
    def run(self) -> None:
        try:
            self._setup_socket()
            self.running = True
            
            print(f"[HTTP-SERVER] Server listening on {self.host}:{self.port}")
            
            while self.running:
                try:
                    events = self.poller.poll(1000)  # 1 second timeout
                    
                    for fd, event in events:
                        sock = self.fd_to_socket.get(fd)
                        if sock is None:
                            continue
                        
                        if sock == self.sock:
                            # Server socket - accept new connection
                            self._accept_client()
                        elif event & select.POLLIN:
                            # Client socket - read data
                            self._read_from_client(sock)
                        elif event & (select.POLLHUP | select.POLLERR):
                            # Client disconnected or error
                            self._cleanup_client(sock)
                
                except KeyboardInterrupt:
                    print("\n[HTTP-SERVER] Shutdown requested")
                    break
                except Exception as e:
                    print(f"[HTTP-SERVER] Error in event loop: {e}")
        
        finally:
            self.shutdown()
    
    def shutdown(self) -> None:
        self.running = False
        
        # Close all client sockets
        for sock in list(self.fd_to_socket.values()):
            try:
                self.poller.unregister(sock.fileno())
            except:
                pass
            try:
                sock.close()
            except:
                pass
        
        # Close server socket
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        
        print("[HTTP-SERVER] Server shutdown complete")


# useful middleware examples

# adding CORS later if needed
def cors_middleware(request: HTTPRequest) -> Optional[HTTPResponse]:
    # This is applied before handler, returning None lets handler proceed
    return None


# adding auth middleware for user authorization and role support
def auth_middleware(required_paths: List[str]):
    def middleware(request: HTTPRequest) -> Optional[HTTPResponse]:
        for path in required_paths:
            if request.path.startswith(path):
                auth = request.headers.get("authorization", "")
                if not auth.startswith("Bearer "):
                    return HTTPResponse(401, b"Unauthorized")
        return None
    return middleware

def logging_middleware(request: HTTPRequest) -> Optional[HTTPResponse]:
    print(f"[REQUEST] {request.method} {request.path}")
    return None


# utility functions

def parse_query_params(query_string: str) -> Dict[str, str]:
    params = {}
    if query_string:
        for pair in query_string.split("&"):
            if "=" in pair:
                key, value = pair.split("=", 1)
                params[key] = value
    return params


def get_content_type(file_extension: str) -> str:
    return HTTPResponse.CONTENT_TYPES.get(
        file_extension.lower(),
        "application/octet-stream"
    )


# example usage
# if __name__ == "__main__":
#     server = HTTPServer(port=8000)
#     
#     @server.get("/")
#     def home(request: HTTPRequest):
#         return HTTPResponse.html("<h1>Hello, World!</h1>")
#     
#     @server.get("/api/data")
#     def get_data(request: HTTPRequest):
#         return HTTPResponse.json({"status": "ok", "data": [1, 2, 3]})
#     
#     @server.post("/api/echo")
#     def echo(request: HTTPRequest):
#         try:
#             data = json.loads(request.body)
#             return HTTPResponse.json({"echo": data})
#         except:
#             return HTTPResponse(400, b"Bad Request")
#     
#     server.run()
