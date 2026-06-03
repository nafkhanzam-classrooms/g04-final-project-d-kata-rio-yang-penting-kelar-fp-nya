import struct
import logging
from typing_extensions import Optional

logger = logging.getLogger(__name__)

class PacketHeader:
    
    # initialize the packet header class with struct format that can be passed as the new class instance argument
    # example: PacketHeader("!IHHH") creates 8-byte header with 4-byte int + 2 shorts
    def __init__(self, format_string: str, field_names: Optional[list] = None):
        # format_string will be used as the argument of the struct.pack function to create the header
        # field_names is an optional list for field names used for documentation purpose
        self.format = format_string
        self.size = struct.calcsize(format_string)
        self.field_names = field_names or []
        
        if self.field_names and len(self.field_names) != self._count_fields():
            logger.warning(f"Field names count mismatch: {len(self.field_names)} != {self._count_fields()}")
    
    # functions with _ prefix indicates it is a private function and normally would not be called outside of this class
    def _count_fields(self) -> int :
        # count the number of fields in the format string provided by the parameter
        # Remove endianness markers
        fmt = self.format.lstrip('!@=<>')
        count = 0
        for char in fmt:
            if char.isalpha():
                count += 1
        return count
    
    def pack(self, *values) -> bytes :
        # *values variable is for matching the format specification and passes it into the struct.pack function
        # if the struct.pack successfully created, the bytes for the struct will be returned, otherwise an error will be raised
        try:
            return struct.pack(self.format, *values)
        except struct.error as e:
            logger.error(f"Pack error with format {self.format}: {e}")
            raise
    
    def unpack(self, data: bytes) -> tuple :
        # the opposite implementation of the pack function
        # data argument is for the incoming packet and will be unpacked by the current context of the message / packet format
        # returns tuple if the unpacking process successfull, otherwise an error will be raised
        if len(data) < self.size:
            raise ValueError(f"Insufficient data: {len(data)} < {self.size}")
        try:
            return struct.unpack(self.format, data[:self.size])
        except struct.error as e:
            logger.error(f"Unpack error with format {self.format}: {e}")
            raise
    
    def unpack_dict(self, data: bytes) -> dict:
        # unpack header into dictionary using the field names
        values = self.unpack(data)
        if self.field_names:
            return dict(zip(self.field_names, values))
        return {"values": values}


class FramedMessage:
    # Custom protocol for framed messages with length prefix, the format is ">I" followed by payload
    
    LENGTH_FORMAT = ">I"  # Big-endian unsigned int (4 bytes)
    LENGTH_SIZE = 4
    MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB

    # functions with @staticmethod above can be called directly without having to create an instance of the FramedMessage class
    
    @staticmethod
    def frame(data: bytes) -> bytes:
        # frame the data with length prefix, fails if the message too large above the MAX_MESSAGE_SIZE
        if len(data) > FramedMessage.MAX_MESSAGE_SIZE:
            raise ValueError(f"Message too large: {len(data)}")
        
        length_header = struct.pack(FramedMessage.LENGTH_FORMAT, len(data))
        return length_header + data
    
    @staticmethod
    def unframe_single(data: bytes) -> tuple:
        # extract single framed message from the received buffer message
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
    def unframe_all(data: bytes) -> tuple:
        # extract all framed messages from the received buffer, an wrapper for the unframe_single function
        messages = []
        remaining = data
        
        while remaining:
            msg, remaining = FramedMessage.unframe_single(remaining)
            if msg is None:
                break
            messages.append(msg)
        
        return messages, remaining


class BufferedReader:
    # handles the buffered reading with support for custom headers and framed messages
    
    def __init__(self, header: Optional[PacketHeader] = None, max_buffer_size: int = 1024 * 1024):
        # header is optional, buffer is set to empty for the init, max_buffer_size if not specified is 1024 * 1024 bytes
        self.header = header
        self.buffer = b""
        self.max_buffer_size = max_buffer_size
    
    def feed(self, data: bytes):
        """Add data to buffer."""
        # add data to the buffer, similar to the traditional while loop until the data is invalid (reaches the end)
        # if buffer overflowed, an warning and error will be raised
        self.buffer += data
        if len(self.buffer) > self.max_buffer_size:
            logger.warning(f"Buffer size exceeded: {len(self.buffer)} > {self.max_buffer_size}")
            raise BufferError("Buffer overflow")
    
    def has_header(self) -> bool:
        # checks if the buffer contains comlete header or not
        if self.header is None:
            return False
        return len(self.buffer) >= self.header.size
    
    def read_header(self) -> tuple:
        # read and consume the header from the buffered message/packet
        if not self.has_header():
            raise ValueError("Incomplete header in buffer")
        
        header_data = self.buffer[:self.header.size]
        self.buffer = self.buffer[self.header.size:]
        
        return self.header.unpack(header_data)
    
    def read_header_dict(self) -> dict:
        # read header as dictionary format
        values = self.read_header()
        if self.header.field_names:
            return dict(zip(self.header.field_names, values))
        return {"values": values}
    
    def has_framed_message(self) -> bool:
        # checks if the buffer contains a completed framed message
        if len(self.buffer) < FramedMessage.LENGTH_SIZE:
            return False
        
        length = struct.unpack(FramedMessage.LENGTH_FORMAT, 
                              self.buffer[:FramedMessage.LENGTH_SIZE])[0]
        return len(self.buffer) >= FramedMessage.LENGTH_SIZE + length
    
    def read_framed_message(self) -> bytes:
        # read framed message using the unframe_single function, returns the message
        if not self.has_framed_message():
            raise ValueError("Incomplete message in buffer")
        
        msg, self.buffer = FramedMessage.unframe_single(self.buffer)
        return msg
    
    def read_all_framed_messages(self) -> list:
        # read all framed messasge within one buffer, a wrapper for the unframe_all function
        messages, self.buffer = FramedMessage.unframe_all(self.buffer)
        return messages
    
    def peek_buffer(self, size: Optional[int] = None) -> bytes:
        # do peek operation at the buffer without consuming the content of the buffer nor use the buffer
        return self.buffer[:size] if size else self.buffer
    
    def clear_buffer(self):
        self.buffer = b""
    
    def buffer_size(self) -> int:
        return len(self.buffer)
