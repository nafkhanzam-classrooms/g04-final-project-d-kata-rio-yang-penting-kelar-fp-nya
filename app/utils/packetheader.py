import struct
import logging
from typing import Optional, List, Tuple, Dict, Any

logger = logging.getLogger(__name__)

class PacketHeader:
    """Handles binary packet header formatting, packing, and unpacking using struct."""
    
    def __init__(self, format_string: str, field_names: Optional[List[str]] = None) -> None:
        self.format = format_string
        self.size = struct.calcsize(format_string)
        self.field_names = field_names or []
        
        if self.field_names and len(self.field_names) != self._count_fields():
            logger.warning(f"Field names count mismatch: {len(self.field_names)} != {self._count_fields()}")
    
    def _count_fields(self) -> int:
        fmt = self.format.lstrip('!@=<>')
        return sum(1 for char in fmt if char.isalpha())
    
    def pack(self, *values: Any) -> bytes:
        try:
            return struct.pack(self.format, *values)
        except struct.error as e:
            logger.error(f"Pack error with format {self.format}: {e}")
            raise
    
    def unpack(self, data: bytes) -> Tuple[Any, ...]:
        if len(data) < self.size:
            raise ValueError(f"Insufficient data: {len(data)} < {self.size}")
        try:
            return struct.unpack(self.format, data[:self.size])
        except struct.error as e:
            logger.error(f"Unpack error with format {self.format}: {e}")
            raise
    
    def unpack_dict(self, data: bytes) -> Dict[str, Any]:
        values = self.unpack(data)
        if self.field_names:
            return dict(zip(self.field_names, values))
        return {"values": values}


class FramedMessage:
    """Custom protocol for framed messages with a 4-byte big-endian length prefix."""
    
    LENGTH_FORMAT = ">I"
    LENGTH_SIZE = 4
    MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB
    
    @staticmethod
    def frame(data: bytes) -> bytes:
        if len(data) > FramedMessage.MAX_MESSAGE_SIZE:
            raise ValueError(f"Message too large: {len(data)}")
        
        length_header = struct.pack(FramedMessage.LENGTH_FORMAT, len(data))
        return length_header + data
    
    @staticmethod
    def unframe_single(data: bytes) -> Tuple[Optional[bytes], bytes]:
        if len(data) < FramedMessage.LENGTH_SIZE:
            return None, data
        
        length = struct.unpack(FramedMessage.LENGTH_FORMAT, data[:FramedMessage.LENGTH_SIZE])[0]
        
        if length > FramedMessage.MAX_MESSAGE_SIZE:
            raise ValueError(f"Message length exceeds limit: {length}")
        
        total_needed = FramedMessage.LENGTH_SIZE + length
        if len(data) < total_needed:
            return None, data
        
        message = data[FramedMessage.LENGTH_SIZE:total_needed]
        remaining = data[total_needed:]
        
        return message, remaining
    
    @staticmethod
    def unframe_all(data: bytes) -> Tuple[List[bytes], bytes]:
        messages = []
        remaining = data
        
        while remaining:
            msg, next_remaining = FramedMessage.unframe_single(remaining)
            if msg is None:
                break
            messages.append(msg)
            remaining = next_remaining
        
        return messages, remaining


class BufferedReader:
    """Handles buffered reading with support for packet headers and framed messages."""
    
    def __init__(self, header: Optional[PacketHeader] = None, max_buffer_size: int = 1024 * 1024) -> None:
        self.header = header
        self.buffer = bytearray()
        self.max_buffer_size = max_buffer_size
    
    def feed(self, data: bytes) -> None:
        self.buffer.extend(data)
        if len(self.buffer) > self.max_buffer_size:
            logger.warning(f"Buffer size exceeded: {len(self.buffer)} > {self.max_buffer_size}")
            raise BufferError("Buffer overflow")
    
    def has_header(self) -> bool:
        if self.header is None:
            return False
        return len(self.buffer) >= self.header.size
    
    def read_header(self) -> Tuple[Any, ...]:
        if not self.has_header():
            raise ValueError("Incomplete header in buffer")
        
        assert self.header is not None
        header_data = bytes(self.buffer[:self.header.size])
        del self.buffer[:self.header.size]
        
        return self.header.unpack(header_data)
    
    def read_header_dict(self) -> Dict[str, Any]:
        values = self.read_header()
        assert self.header is not None
        if self.header.field_names:
            return dict(zip(self.header.field_names, values))
        return {"values": values}
    
    def has_framed_message(self) -> bool:
        if len(self.buffer) < FramedMessage.LENGTH_SIZE:
            return False
        
        length = struct.unpack(FramedMessage.LENGTH_FORMAT, 
                               self.buffer[:FramedMessage.LENGTH_SIZE])[0]
        return len(self.buffer) >= FramedMessage.LENGTH_SIZE + length
    
    def read_framed_message(self) -> bytes:
        if not self.has_framed_message():
            raise ValueError("Incomplete message in buffer")
        
        msg, remaining = FramedMessage.unframe_single(bytes(self.buffer))
        self.buffer = bytearray(remaining)
        return msg or b""
    
    def read_all_framed_messages(self) -> List[bytes]:
        messages, remaining = FramedMessage.unframe_all(bytes(self.buffer))
        self.buffer = bytearray(remaining)
        return messages
    
    def peek_buffer(self, size: Optional[int] = None) -> bytes:
        return bytes(self.buffer[:size]) if size else bytes(self.buffer)
    
    def clear_buffer(self) -> None:
        self.buffer.clear()
    
    def buffer_size(self) -> int:
        return len(self.buffer)
