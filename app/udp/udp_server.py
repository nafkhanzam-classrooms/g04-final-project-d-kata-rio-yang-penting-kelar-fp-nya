import socket
import struct
import time
import logging
from typing import Tuple, Optional, List
from utils.packetheader import PacketHeader

logger = logging.getLogger(__name__)

class UDPSocket:
    # wrapper around the UDP socket with optional custom header support 
    
    def __init__(self, local_ip: str = "127.0.0.1", local_port: int = 5991, 
                 header: Optional[PacketHeader] = None):
        # IP defaults to bind to 0.0.0.0, and the port if not specified will default fallback to 5991
        # using socket.SO_REUSEADDR for handling if the port is/was used
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        self.header = header
        self.local_ip = local_ip
        self.local_port = local_port
        
        if local_ip:
            self.sock.bind((local_ip, local_port))
            bound_addr = self.sock.getsockname()
            logger.info(f"UDP socket bound to {bound_addr}")
            self.local_port = bound_addr[1]
    
    def send(self, data: bytes, remote_addr: Tuple[str, int], timeout: Optional[float] = None) -> None :
        # send a data in bytes format to the remote address using the sendto function
        if timeout:
            self.sock.settimeout(timeout)
        
        try:
            self.sock.sendto(data, remote_addr)
            logger.debug(f"Sent {len(data)} bytes to {remote_addr}")
        except socket.timeout:
            logger.error(f"Send timeout to {remote_addr}")
            raise
        finally:
            if timeout:
                self.sock.settimeout(None)
    
    def recv(self, max_size: int = 65535, timeout: Optional[float] = None) -> Tuple[bytes, Tuple[str, int]]:
        # receive any data from any remote address, can specify the max_size of the bytes that can be received by tge server, 
        # also there is optional float socket timeout
        if timeout:
            self.sock.settimeout(timeout)
        
        try:
            data, addr = self.sock.recvfrom(max_size)
            logger.debug(f"Received {len(data)} bytes from {addr}")
            return data, addr
        except socket.timeout:
            logger.warning("Recv timeout")
            raise
        finally:
            if timeout:
                self.sock.settimeout(None)
    
    def send_with_header(self, header_values: tuple, payload: bytes, 
                        remote_addr: Tuple[str, int]):
        # send packet with header packing provided by the function argument
        # header_bytes + payload
        # remote_addr consists of host and the port for the recepient of the packet
        if not self.header:
            raise RuntimeError("Header not configured")
        
        header_bytes = self.header.pack(*header_values)
        self.send(header_bytes + payload, remote_addr)
    
    def recv_with_header(self, max_payload_size: int = 65535) -> Tuple[tuple, bytes, Tuple[str, int]]:
        # receive a packet with a custom header with maximum payload size is 65535 bytes
        # unpacked with the class header set before
        if not self.header:
            raise RuntimeError("Header not configured")
        
        data, addr = self.recv(max_payload_size + self.header.size)
        
        header_values = self.header.unpack(data)
        payload = data[self.header.size:]
        
        return header_values, payload, addr
    
    def get_local_address(self) -> Tuple[str, int]:
        # get the local address of the server, returns the host and the port
        return self.sock.getsockname()
    
    def close(self):
        # close the socket for the UDP socket
        try:
            self.sock.close()
            logger.info("UDP socket closed")
        except Exception as e:
            logger.error(f"Error closing UDP socket: {e}")
    
    def __del__(self):
        # magic function to ensure the deletion/closing the socket
        try:
            self.sock.close()
        except:
            pass


class UDPSegmentedSender:
    # Sends large payloads segmented into UDP packets.
    # Useful for streaming or transferring data larger than MTU.
    
    def __init__(self, remote_addr: Tuple[str, int], udp_socket: UDPSocket, segment_header: PacketHeader,
                 max_payload_size: int = 1200):
        # init with remote_addr destionation using tuple of host IP and port
        # udp_socket for the connection to be used as the segmented UDP packets sending
        # max_payload_size for defining maximum payload size in bytes for per paccket
        # segment_header is the  format header for the segment metadata 
        # segment_id, chunk_id, total_chunks, payload_len

        self.remote_addr = remote_addr
        self.udp_socket = udp_socket
        self.max_payload_size = max_payload_size
        self.segment_header = segment_header
        self.segment_id = 0
        self.pacing_delay = 0  # seconds between packets
    
    def set_pacing(self, delay: float):
        # sst the delays in seconds for sending between packet to reduce burst loss
        self.pacing_delay = delay
    
    def send_data(self, data: bytes) -> int:
        # send data segmented into UDP packets
        # segments the raw data using the internal private function _segment_data
        # returns the sum of the bytes sent
        segments = self._segment_data(data)
        total_sent = 0
        
        for segment in segments:
            total_sent += len(segment)
            self.udp_socket.send(segment, self.remote_addr)
            
            if self.pacing_delay > 0:
                time.sleep(self.pacing_delay)
        
        logger.info(f"Sent {len(segments)} segments, {total_sent} bytes total")
        return total_sent
    
    def _segment_data(self, data: bytes) -> List[bytes]:
        # internal function to segment data into packets
        # assigning each one of the segmented packet with the chunk id appended at the header
        if not self.segment_header:
            raise RuntimeError("Segment header not configured")
        
        # revoked and raises error if the payload_size is too small for header
        payload_size = self.max_payload_size - self.segment_header.size
        if payload_size <= 0:
            raise ValueError("max_payload_size too small for header")
        
        segments = []
        chunk_id = 0
        
        for i in range(0, len(data), payload_size):
            chunk = data[i:i + payload_size]
            payload_len = len(chunk)
            
            # Assuming header format: (segment_id, chunk_id, total_chunks, payload_len)
            # Adjust based on your actual header format
            total_chunks = (len(data) + payload_size - 1) // payload_size
            
            # [IMPORTANT] MODIFY THIS to change the header format
            header = self.segment_header.pack(self.segment_id, chunk_id, total_chunks, payload_len)
            segments.append(header + chunk)
            
            chunk_id += 1
        
        self.segment_id = (self.segment_id + 1) & 0xFFFFFFFF  # Wrap at 32-bit
        return segments
    
    def set_remote_addr(self, remote_addr: Tuple[str, int]):
        # change the remote addr using tuple of dest host IP and port
        self.remote_addr = remote_addr


class UDPSegmentedReceiver:
    # receives and reassambles UDP segment packets into a complete message/s
    
    def __init__(self, segment_header: PacketHeader, timeout: float = 30):
        # segment header for the header format if specified on the opposite server/client
        # timeout for the amount of time to wait for the complete segment reassembly, defaults to 30 seconds (float)
        self.segment_header = segment_header
        self.timeout = timeout
        self.segments = {}  # segment_id -> {chunk_id -> chunk_data}
        self.timestamps = {}  # segment_id -> timestamp
    

    def feed_packet(self, packet: bytes) -> Optional[bytes]:
        # feed a received UDP packet to the segments variable
        if not self.segment_header:
            raise RuntimeError("Segment header not configured")
        
        if len(packet) < self.segment_header.size:
            raise ValueError("Packet too small for header")
        
        header_values = self.segment_header.unpack(packet)
        # Assuming: (segment_id, chunk_id, total_chunks, payload_len)
        segment_id = header_values[0]
        chunk_id = header_values[1]
        total_chunks = header_values[2]
        payload_len = header_values[3]
        
        payload = packet[self.segment_header.size:self.segment_header.size + payload_len]
        
        # Initialize segment tracking
        if segment_id not in self.segments:
            self.segments[segment_id] = {}
            self.timestamps[segment_id] = time.time()
        
        # Store chunk
        self.segments[segment_id][chunk_id] = payload
        
        # Check if complete
        if len(self.segments[segment_id]) == total_chunks:
            reassembled = self._reassemble(segment_id, total_chunks)
            del self.segments[segment_id]
            del self.timestamps[segment_id]
            return reassembled
        
        # Cleanup old segments
        self._cleanup_expired()
        
        return None
    
    def _reassemble(self, segment_id: int, total_chunks: int) -> bytes:
        # reassamble the chunked segments into a complete original packet message
        result = b""
        for i in range(total_chunks):
            if i not in self.segments[segment_id]:
                raise RuntimeError(f"Missing chunk {i} of segment {segment_id}")
            result += self.segments[segment_id][i]
        return result
    
    def _cleanup_expired(self):
        # removes the segments that timed out
        now = time.time()
        expired = [sid for sid, ts in self.timestamps.items() 
                  if now - ts > self.timeout]
        
        for segment_id in expired:
            logger.warning(f"Segment {segment_id} reassembly timeout")
            del self.segments[segment_id]
            del self.timestamps[segment_id]
    
    def pending_segments(self) -> dict:
        # get the status of the incomplete segments
        return {sid: {
            'chunks_received': len(self.segments[sid]),
            'age_seconds': time.time() - self.timestamps[sid]
        } for sid in self.segments}
