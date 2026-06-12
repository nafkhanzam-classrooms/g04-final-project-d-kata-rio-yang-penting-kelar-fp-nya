import json
import time
import threading
import socket
from typing import Dict, List, Optional, Any


class SSEClient:
    """Represents a single SSE-connected client socket."""

    def __init__(self, client_socket: socket.socket, channel: str, user_id: Optional[int] = None):
        self.socket = client_socket
        self.channel = channel
        self.user_id = user_id
        self.connected_at = time.time()
        self.last_ping = time.time()

    def send_event(self, event_type: str, data: Any) -> bool:
        """
        Send an SSE event to this client.
        Returns False if the client is disconnected.
        """
        try:
            if isinstance(data, dict) or isinstance(data, list):
                payload = json.dumps(data)
            else:
                payload = str(data)

            # SSE format: event: <type>\ndata: <payload>\n\n
            message = f"event: {event_type}\ndata: {payload}\n\n"
            self.socket.sendall(message.encode("utf-8"))
            return True
        except (BrokenPipeError, OSError, ConnectionResetError):
            return False

    def send_comment(self, comment: str) -> bool:
        """Send an SSE comment (keepalive ping)."""
        try:
            self.socket.sendall(f": {comment}\n\n".encode("utf-8"))
            self.last_ping = time.time()
            return True
        except (BrokenPipeError, OSError, ConnectionResetError):
            return False


class SSEManager:
    """
    Central SSE connection manager.
    Maintains a registry of channel -> [SSEClient] mappings.
    Thread-safe for concurrent access.
    """

    _instance: Optional["SSEManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        # channel_name -> list of SSEClient
        self.channels: Dict[str, List[SSEClient]] = {}
        self._channel_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "SSEManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def subscribe(self, channel: str, client_socket: socket.socket, user_id: Optional[int] = None) -> SSEClient:
        """Register a client socket for SSE events on a channel."""
        client = SSEClient(client_socket, channel, user_id)

        with self._channel_lock:
            if channel not in self.channels:
                self.channels[channel] = []
            self.channels[channel].append(client)

        print(f"[SSE] Client subscribed to channel '{channel}' (total: {len(self.channels[channel])})")
        return client

    def unsubscribe(self, channel: str, client_socket: socket.socket):
        """Remove a client socket from a channel."""
        with self._channel_lock:
            if channel in self.channels:
                self.channels[channel] = [
                    c for c in self.channels[channel]
                    if c.socket != client_socket
                ]
                if not self.channels[channel]:
                    del self.channels[channel]

    def unsubscribe_socket(self, client_socket: socket.socket):
        """Remove a socket from ALL channels it belongs to."""
        with self._channel_lock:
            for channel in list(self.channels.keys()):
                self.channels[channel] = [
                    c for c in self.channels[channel]
                    if c.socket != client_socket
                ]
                if not self.channels[channel]:
                    del self.channels[channel]

    def publish(self, channel: str, event_type: str, data: Any):
        """
        Push an event to all subscribers on a channel.
        Automatically cleans up dead connections.
        """
        dead_clients = []

        with self._channel_lock:
            clients = list(self.channels.get(channel, []))

        for client in clients:
            if not client.send_event(event_type, data):
                dead_clients.append(client)

        # Cleanup dead connections
        if dead_clients:
            with self._channel_lock:
                if channel in self.channels:
                    self.channels[channel] = [
                        c for c in self.channels[channel]
                        if c not in dead_clients
                    ]
                    if not self.channels[channel]:
                        del self.channels[channel]

            for dc in dead_clients:
                try:
                    dc.socket.close()
                except:
                    pass

            print(f"[SSE] Cleaned up {len(dead_clients)} dead clients from '{channel}'")

    def get_subscriber_count(self, channel: str) -> int:
        with self._channel_lock:
            return len(self.channels.get(channel, []))

    def get_all_channels(self) -> List[str]:
        with self._channel_lock:
            return list(self.channels.keys())

    def is_socket_subscribed(self, client_socket: socket.socket) -> bool:
        """Check if a socket is registered as an SSE client in any channel."""
        with self._channel_lock:
            for clients in self.channels.values():
                for c in clients:
                    if c.socket == client_socket:
                        return True
        return False


class SSEResponse:
    """
    Marker response object returned by handlers to indicate
    that this connection should be kept alive as an SSE stream.
    The HTTP server detects this type and skips cleanup.
    """

    def __init__(self, channel: str, user_id: Optional[int] = None):
        self.channel = channel
        self.user_id = user_id

    def get_headers_bytes(self) -> bytes:
        """Return the initial SSE HTTP response headers."""
        headers = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/event-stream\r\n"
            "Cache-Control: no-cache\r\n"
            "Connection: keep-alive\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "X-Accel-Buffering: no\r\n"
            "\r\n"
        )
        return headers.encode("utf-8")
