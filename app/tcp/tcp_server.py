import socket
import select
import logging
import time
from typing import Tuple, Optional, Callable, Dict, Any

from utils.packetheader import PacketHeader, FramedMessage, BufferedReader

logger = logging.getLogger(__name__)


class TCPSocket:
    """
    Wrapper for a TCP socket providing connection management, timeouts, and message framing.
    """
    
    def __init__(self, socket_obj: Optional[socket.socket] = None) -> None:
        self.sock: socket.socket = socket_obj or socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.remote_addr: Optional[Tuple[str, int]] = None
    
    def connect(self, host: str, port: int, timeout: Optional[float] = 10.0) -> None:
        """
        Establishes a connection to the specified host and port.
        """
        if timeout is not None:
            self.sock.settimeout(timeout)
        
        try:
            self.sock.connect((host, port))
            self.remote_addr = (host, port)
            logger.info(f"Connected to {host}:{port}")
        except socket.timeout:
            logger.error(f"Connection timeout to {host}:{port}")
            raise
        except Exception as e:
            logger.error(f"Connection failed to {host}:{port}: {e}")
            raise
        finally:
            if timeout is not None:
                self.sock.settimeout(None)
    
    def send(self, data: bytes, timeout: Optional[float] = 10.0) -> int:
        """
        Transmits raw byte data over the socket.
        """
        if timeout is not None:
            self.sock.settimeout(timeout)
        
        try:
            self.sock.sendall(data)
            logger.debug(f"Sent {len(data)} bytes")
            return len(data)
        except socket.timeout:
            logger.error("Send timeout")
            raise
        except Exception as e:
            logger.error(f"Send failed: {e}")
            raise
        finally:
            if timeout is not None:
                self.sock.settimeout(None)
    
    def recv(self, max_size: int = 4096, timeout: Optional[float] = 10.0) -> bytes:
        """
        Receives raw byte data up to max_size.
        """
        if timeout is not None:
            self.sock.settimeout(timeout)
        
        try:
            data = self.sock.recv(max_size)
            if data:
                logger.debug(f"Received {len(data)} bytes")
            return data
        except socket.timeout:
            logger.warning("Receive timeout")
            raise
        except Exception as e:
            logger.error(f"Receive failed: {e}")
            raise
        finally:
            if timeout is not None:
                self.sock.settimeout(None)
    
    def send_framed(self, data: bytes) -> None:
        """
        Encapsulates and sends data as a framed message.
        """
        self.send(FramedMessage.frame(data))
    
    def get_remote_address(self) -> Optional[Tuple[str, int]]:
        try:
            return self.sock.getpeername()
        except OSError:
            return None
    
    def set_blocking(self, blocking: bool = False) -> None:
        self.sock.setblocking(blocking)
    
    def close(self) -> None:
        try:
            self.sock.close()
            if self.remote_addr:
                logger.info(f"Socket closed ({self.remote_addr})")
        except OSError as e:
            logger.error(f"Error closing socket: {e}")
    
    def get_fileno(self) -> int:
        return self.sock.fileno()


class TCPServer:
    """
    Asynchronous TCP Server utilizing epoll for multiplexing.
    Handles client connections, buffering, and framed message processing.
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 5000,
                 backlog: int = 5, header: Optional[PacketHeader] = None) -> None:
        self.host = host
        self.port = port
        self.header = header
        
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((host, port))
        self.server_sock.listen(backlog)
        self.server_sock.setblocking(False)
        
        self.epoll = select.epoll()
        self.epoll.register(self.server_sock.fileno(), select.EPOLLIN)
        
        self.clients: Dict[int, TCPSocket] = {}
        self.buffers: Dict[int, BufferedReader] = {}
        self.client_data: Dict[int, Dict[str, Any]] = {}
        
        self.on_connect: Optional[Callable[[int, Tuple[str, int]], None]] = None
        self.on_disconnect: Optional[Callable[[int, Tuple[str, int]], None]] = None
        self.on_message: Optional[Callable[[int, bytes], None]] = None
        self.on_data: Optional[Callable[[int, bytes], None]] = None
        
        logger.info(f"TCP Server listening on {host}:{port}")
    
    def register_callbacks(self, on_connect: Optional[Callable], 
                           on_disconnect: Optional[Callable],
                           on_message: Optional[Callable],
                           on_data: Optional[Callable]) -> None:
        """
        Registers event callbacks for connection lifecycle and data reception.
        """
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_message = on_message
        self.on_data = on_data
    
    def broadcast_message(self, message: bytes, sender_fd: Optional[int] = None, exclude_fd: Optional[int] = None) -> None:
        """
        Broadcasts a framed message to all connected clients, optionally excluding a specific client.
        """
        framed_data = FramedMessage.frame(message)
        
        for fd, client in self.clients.items():
            if fd in (exclude_fd, sender_fd):
                continue
            
            try:
                client.send(framed_data)
            except Exception as e:
                logger.warning(f"Broadcast to {fd} failed: {e}")
    
    def broadcast_data(self, data: bytes, exclude_fd: Optional[int] = None) -> None:
        """
        Broadcasts raw data to all connected clients.
        """
        for fd, client in self.clients.items():
            if fd == exclude_fd:
                continue
            
            try:
                client.send(data)
            except Exception as e:
                logger.warning(f"Broadcast to {fd} failed: {e}")
    
    def send_to_client(self, fd: int, message: bytes, framed: bool = True) -> None:
        if fd not in self.clients:
            logger.warning(f"Client {fd} not found")
            return
        
        try:
            if framed:
                self.clients[fd].send_framed(message)
            else:
                self.clients[fd].send(message)
        except Exception as e:
            logger.error(f"Send to {fd} failed: {e}")
            self._handle_disconnect(fd)
    
    def get_client_data(self, fd: int) -> Dict[str, Any]:
        return self.client_data.setdefault(fd, {})
    
    def _handle_accept(self) -> None:
        try:
            conn, addr = self.server_sock.accept()
            conn.setblocking(False)
            
            fd = conn.fileno()
            self.clients[fd] = TCPSocket(conn)
            self.buffers[fd] = BufferedReader(self.header)
            
            self.epoll.register(fd, select.EPOLLIN)
            logger.info(f"Client accepted: {addr} (fd={fd})")
            
            if self.on_connect:
                self.on_connect(fd, addr)
        except Exception as e:
            logger.error(f"Accept error: {e}")
    
    def _handle_disconnect(self, fd: int) -> None:
        client = self.clients.pop(fd, None)
        if not client:
            return
        
        addr = client.get_remote_address()
        
        try:
            self.epoll.unregister(fd)
        except OSError:
            pass
        
        client.close()
        self.buffers.pop(fd, None)
        self.client_data.pop(fd, None)
        
        logger.info(f"Client disconnected: {addr} (fd={fd})")
        
        if self.on_disconnect and addr:
            self.on_disconnect(fd, addr)
    
    def _handle_read(self, fd: int) -> None:
        client = self.clients.get(fd)
        if not client:
            return
        
        try:
            data = client.recv()
            if not data:
                self._handle_disconnect(fd)
                return
            
            self.buffers[fd].feed(data)
            
            if self.on_message:
                for msg in self.buffers[fd].read_all_framed_messages():
                    self.on_message(fd, msg)
            elif self.on_data:
                self.on_data(fd, data)
                
        except Exception as e:
            logger.error(f"Read error from {fd}: {e}")
            self._handle_disconnect(fd)
    
    def run(self, timeout: float = 1.0, max_events: int = 10) -> bool:
        """
        Executes a single iteration of the epoll event loop.
        """
        try:
            events = self.epoll.poll(timeout, max_events)
            
            for fd, event in events:
                if fd == self.server_sock.fileno():
                    self._handle_accept()
                elif event & select.EPOLLIN:
                    self._handle_read(fd)
                elif event & (select.EPOLLERR | select.EPOLLHUP):
                    self._handle_disconnect(fd)
            
            return True
        except Exception as e:
            logger.error(f"Epoll error: {e}")
            return False
    
    def run_forever(self, timeout: float = 1.0) -> None:
        """
        Runs the epoll event loop continuously.
        """
        logger.info("Server running (press Ctrl+C to stop)")
        try:
            while self.run(timeout):
                pass
        except KeyboardInterrupt:
            logger.info("Server shutting down...")
        finally:
            self.close()
    
    def close(self) -> None:
        for fd in list(self.clients.keys()):
            self._handle_disconnect(fd)
        
        try:
            self.epoll.close()
        except OSError:
            pass
        
        try:
            self.server_sock.close()
        except OSError:
            pass
        
        logger.info("Server closed")


class TCPClient:
    """
    Robust TCP Client supporting auto-reconnection and message framing.
    """
    
    def __init__(self, host: str, port: int, auto_reconnect: bool = True) -> None:
        self.host = host
        self.port = port
        self.auto_reconnect = auto_reconnect
        
        self.socket = TCPSocket()
        self.connected = False
        self.buffer = BufferedReader()
        
        self._connect()
    
    def _connect(self) -> None:
        try:
            self.socket.connect(self.host, self.port, timeout=5.0)
            self.connected = True
            logger.info(f"Connected to {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self.connected = False
    
    def send_message(self, message: bytes) -> None:
        if not self.connected and self.auto_reconnect:
            self._connect()
            
        if not self.connected:
            raise RuntimeError("Not connected")
            
        try:
            self.socket.send_framed(message)
        except Exception as e:
            logger.error(f"Send failed: {e}")
            self.connected = False
            if self.auto_reconnect:
                self._connect()
            raise
    
    def send_data(self, data: bytes) -> None:
        if not self.connected and self.auto_reconnect:
            self._connect()
            
        if not self.connected:
            raise RuntimeError("Not connected")
            
        try:
            self.socket.send(data)
        except Exception as e:
            logger.error(f"Send failed: {e}")
            self.connected = False
            raise
    
    def recv_message(self, timeout: float = 5.0) -> Optional[bytes]:
        deadline = time.time() + timeout
        
        while time.time() < deadline:
            if self.buffer.has_framed_message():
                return self.buffer.read_framed_message()
            
            try:
                data = self.socket.recv(4096, timeout=0.1)
                
                if not data:
                    self.connected = False
                    if self.auto_reconnect:
                        self._connect()
                    return None
                
                self.buffer.feed(data)
            
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"Receive failed: {e}")
                self.connected = False
                raise
                
        return None
    
    def recv_data(self, max_size: int = 4096, timeout: float = 5.0) -> Optional[bytes]:
        try:
            return self.socket.recv(max_size, timeout)
        except Exception as e:
            logger.error(f"Receive failed: {e}")
            self.connected = False
            raise
    
    def close(self) -> None:
        if self.socket:
            self.socket.close()
        self.connected = False

