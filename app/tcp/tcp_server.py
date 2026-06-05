import socket
import select
import logging
import time
from typing import Tuple, Optional, Callable, Dict, Any
from app.utils.packetheader import PacketHeader, FramedMessage, BufferedReader

logger = logging.getLogger(__name__)

class TCPSocket:
    # TCP custom socket wrapper class with optional custom header support
    
    def __init__(self, socket_obj: Optional[socket.socket] = None):
        if socket_obj:
            self.sock = socket_obj
        else:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        self.remote_addr = None
    
    def connect(self, host: str, port: int, timeout: float = 10):
        # conntect to the remote server using the tuple of hostname/IP and port, optional timeout value in seconds if the connections timed out, defaults to 10 seconds
        if timeout:
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
            if timeout:
                self.sock.settimeout(None)
    
    def send(self, data: bytes, timeout: float = 10) -> int:
        # sends data in bytes with optional send timeout in seconds defaults by 10 seconds
        if timeout:
            self.sock.settimeout(timeout)
        
        try:
            sent = self.sock.sendall(data)
            logger.debug(f"Sent {len(data)} bytes")
            return len(data)
        except socket.timeout:
            logger.error("Send timeout")
            raise
        finally:
            if timeout:
                self.sock.settimeout(None)
    
    def recv(self, max_size: int = 4096, timeout: float = 10) -> bytes:
        # receives data packet with maximum byte size that can be received, optional timeout value in seconds defaults by 10 secs
        if timeout:
            self.sock.settimeout(timeout)
        
        try:
            data = self.sock.recv(max_size)
            if data:
                logger.debug(f"Received {len(data)} bytes")
            return data
        except socket.timeout:
            logger.warning("Recv timeout")
            raise
        finally:
            if timeout:
                self.sock.settimeout(None)
    
    def send_framed(self, data: bytes):
        # send framed message, a wrapper function for the FramedMessage.frame, data is in bytes format
        framed = FramedMessage.frame(data)
        self.send(framed)
    
    def get_remote_address(self) -> Optional[Tuple[str, int]]:
        # get the remote address
        try:
            return self.sock.getpeername()
        except:
            return None
    
    def set_blocking(self, blocking: bool = False):
        # set the blocking mode, defaults to false
        self.sock.setblocking(blocking)
    
    def close(self):
        try:
            self.sock.close()
            logger.info(f"Socket closed ({self.remote_addr})")
        except Exception as e:
            logger.error(f"Error closing socket: {e}")
    
    def get_fileno(self) -> int:
        return self.sock.fileno()


class TCPServer:
    # using select.epoll for multi-client handling, a class for the TCP server 
    # supports custom headers, message frmaing and buffering
    def __init__(self, host: str = "127.0.0.1", port: int = 5000,
                 backlog: int = 5, header: Optional[PacketHeader] = None):
        # optional custom header format
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
        
        # Track connected clients
        self.clients = {}  # fd -> TCPSocket
        self.buffers = {}  # fd -> BufferedReader
        self.client_data = {}  # fd -> arbitrary client state dict
        
        # Callbacks
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None  # For framed messages
        self.on_data = None  # For raw data
        
        logger.info(f"TCP Server listening on {host}:{port}")
    
    def register_callbacks(self, on_connect: Callable, 
                          on_disconnect: Callable,
                          on_message: Callable,
                          on_data: Callable):
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_message = on_message
        self.on_data = on_data
    
    def broadcast_message(self, message: bytes, sender_fd: int, exclude_fd: Optional[int] = None):
        # broadcast a framed message to all clients that are connected
        # exclude_fd to optionally exclude one client
        framed = FramedMessage.frame(message)
        
        for fd, client in self.clients.items():
            if exclude_fd and fd == exclude_fd:
                continue
            if sender_fd and fd == sender_fd:
                continue
            
            try:
                client.send(framed)
            except Exception as e:
                logger.warning(f"Broadcast to {fd} failed: {e}")
    
    def broadcast_data(self, data: bytes, exclude_fd: Optional[int] = None):
        # broadcast raw data to all client, except for the optional excluded client in exclude_fd
        for fd, client in self.clients.items():
            if exclude_fd and fd == exclude_fd:
                continue
            
            try:
                client.send(data)
            except Exception as e:
                logger.warning(f"Broadcast to {fd} failed: {e}")
    
    def send_to_client(self, fd: int, message: bytes, framed: bool = True):
        # send a message to a specific client
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
        # get a client data, if exists will returned the client's fd, if not exists will returns an empty dict
        if fd not in self.client_data:
            self.client_data[fd] = {}
        return self.client_data[fd]
    
    def _handle_accept(self):
        try:
            conn, addr = self.server_sock.accept()
            conn.setblocking(False)
            
            fd = conn.fileno()
            tcp_sock = TCPSocket(conn)
            
            self.clients[fd] = tcp_sock
            self.buffers[fd] = BufferedReader(self.header)
            
            self.epoll.register(fd, select.EPOLLIN)
            
            logger.info(f"Client accepted: {addr} (fd={fd})")
            
            if self.on_connect:
                self.on_connect(fd, addr)
        
        except Exception as e:
            logger.error(f"Accept error: {e}")
    
    def _handle_disconnect(self, fd: int):
        if fd not in self.clients:
            return
        
        addr = self.clients[fd].get_remote_address()
        
        try:
            self.epoll.unregister(fd)
        except:
            pass
        
        try:
            self.clients[fd].close()
        except:
            pass
        
        del self.clients[fd]
        del self.buffers[fd]
        
        if fd in self.client_data:
            del self.client_data[fd]
        
        logger.info(f"Client disconnected: {addr} (fd={fd})")
        
        if self.on_disconnect:
            self.on_disconnect(fd, addr)
    
    def _handle_read(self, fd: int):
        if fd not in self.clients:
            return
        
        try:
            data = self.clients[fd].recv()
            
            if not data:
                # Connection closed
                self._handle_disconnect(fd)
                return
            
            self.buffers[fd].feed(data)
            
            # Process available messages
            if self.on_message:
                messages = self.buffers[fd].read_all_framed_messages()
                for msg in messages:
                    self.on_message(fd, msg)
            elif self.on_data:
                self.on_data(fd, data)
        
        except Exception as e:
            logger.error(f"Read error from {fd}: {e}")
            self._handle_disconnect(fd)
    
    def run(self, timeout: float = 1.0, max_events: int = 10):
        # run the servver event loop and timeout the epool in seconds defaults to 1 second
        # max_events sets the max processing iteration
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
    
    def run_forever(self, timeout: float = 1.0):
        # wrapper to run function to run the server continously until interrupt from the user
        logger.info("Server running (press Ctrl+C to stop)")
        try:
            while self.run(timeout):
                pass
        except KeyboardInterrupt:
            logger.info("Server shutting down...")
            self.close()
    
    def close(self):
        # Close all clients
        for fd in list(self.clients.keys()):
            self._handle_disconnect(fd)
        
        # Close epoll
        try:
            self.epoll.close()
        except:
            pass
        
        # Close server socket
        try:
            self.server_sock.close()
        except:
            pass
        
        logger.info("Server closed")


class TCPClient:
    # simple TCP client with framing support and auto-reconnect
    def __init__(self, host: str, port: int, auto_reconnect: bool = True):
        # sets the auto-reconnect behavior and defaults to true
        self.host = host
        self.port = port
        self.auto_reconnect = auto_reconnect
        
        self.socket: TCPSocket = TCPSocket()
        self.connected = False
        self.buffer = BufferedReader()
        
        self._connect()
    
    def _connect(self):
        # connects to the TCP server
        try:
            self.socket.connect(self.host, self.port, timeout=5.0)
            self.connected = True
            logger.info(f"Connected to {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self.connected = False
    
    def send_message(self, message: bytes):
        # send framed message to the server
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
    
    def send_data(self, data: bytes):
        # send raw data bytes to the server
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
        # receives a single framed message and timed out with the default of 5 seconds
        # using buffered per packet is 4096 bytes
        deadline = time.time() + timeout
        
        while time.time() < deadline:
            if self.buffer.has_framed_message():
                return self.buffer.read_framed_message()
            
            try:
                data = self.socket.recv(4096, timeout=0.1)
                
                if not data:
                    # Connection closed
                    self.connected = False
                    if self.auto_reconnect:
                        self._connect()
                    return None
                
                self.buffer.feed(data)
            
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"Recv failed: {e}")
                self.connected = False
                raise
        
        return None
    
    def recv_data(self, max_size: int = 4096, timeout: float = 5.0) -> Optional[bytes]:
        try:
            return self.socket.recv(max_size, timeout)
        except Exception as e:
            logger.error(f"Recv failed: {e}")
            self.connected = False
            raise
    
    def close(self):
        if self.socket:
            self.socket.close()
        self.connected = False
