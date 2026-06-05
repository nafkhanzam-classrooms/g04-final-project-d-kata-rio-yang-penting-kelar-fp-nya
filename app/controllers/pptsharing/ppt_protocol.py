import struct
from enum import IntEnum
from utils.packetheader import PacketHeader

class TCPCommand(IntEnum):
    # Enum for custom TCP command messages for the PPT sharing protocol
    # used from client to server
    HELLO = 1
    UPLOAD_PPT = 2
    LIST_FILES = 3
    LOAD_FILE = 4
    GET_SLIDE_COUNT = 5
    GO_TO_SLIDE = 6
    NEXT_SLIDE = 7
    PREV_SLIDE = 8
    GET_CURRENT_SLIDE = 9
    START_BROADCAST = 10
    STOP_BROADCAST = 11
    DISCONNECT = 12
    JOIN_AS_PRESENTER = 13  # Request presenter role
    JOIN_AS_VIEWER = 14     # Join as viewer only
    GET_PRESENTER_INFO = 15 # Get current presenter name/info
    BROADCAST_SLIDE_IMAGE = 16


class TCPResponse(IntEnum):
    # custom TCP server response messages to send to clients
    ACK = 100
    ERROR = 101
    FILE_LIST = 102
    SLIDE_COUNT = 103
    CURRENT_SLIDE = 104
    BROADCAST_STARTED = 105
    BROADCAST_STOPPED = 106
    SLIDE_CHANGED = 107
    PRESENTER_ROLE_GRANTED = 108  # You are now presenter
    VIEWER_ROLE_ASSIGNED = 109    # You are viewer only
    PRESENTER_INFO = 110           # Info about current presenter
    NOT_AUTHORIZED = 111           # Only presenter can do this
    SLIDE_IMAGE_START = 112
    SLIDE_IMAGE_CHUNK = 113
    SLIDE_IMAGE_COMPLETE = 114

# custom ppt protocol
# slide image data header: [packet_id][chunk_id][total_chunks][slide_num][payload_len]
SLIDE_DATA_HEADER = PacketHeader(
    format_string="!IHHBH", # the definition are on the field_names section below this line
    field_names=["packet_id", "chunk_id", "total_chunks", "slide_num", "payload_len"]
)

# slide metadata header: [slide_num][width][height][format_len]
SLIDE_METADATA_HEADER = PacketHeader(
    format_string="!HHHI",  
    field_names=["slide_num", "width", "height", "format_len"]
)

# framing utilities
def create_tcp_command(cmd_type: TCPCommand, payload: bytes = b"") -> bytes:
    # creates a tcp command message, the message is cmd_type + payload, returns in bytes format
    return bytes([cmd_type]) + payload


def parse_tcp_command(data: bytes) -> tuple:
    # parce TCP command from incoming packet
    if not data:
        raise ValueError("Empty command")
    
    cmd_type = TCPCommand(data[0])
    payload = data[1:]
    
    return cmd_type, payload


def create_tcp_response(resp_type: TCPResponse, payload: bytes = b"") -> bytes:
    # creates TCP response message using the same method as the create_tcp_command
    return bytes([resp_type]) + payload


def parse_tcp_response(data: bytes) -> tuple:
    if not data:
        raise ValueError("Empty response")
    
    resp_type = TCPResponse(data[0])
    payload = data[1:]
    
    return resp_type, payload


# payload builders for the PPT protocol
# > means using the big-endian formato
# I -> unsigned int (4 bytes)
# H -> unsigned short (2 bytes)
# >H -> 2 byte length
def build_upload_ppt_payload(filename: str) -> bytes:
    # format used: [2-byte filename length][filename], >H + filename in bytes
    name_bytes = filename.encode('utf-8')
    return struct.pack(">H", len(name_bytes)) + name_bytes


def parse_upload_ppt_payload(data: bytes) -> str:
    # uses the >H + filename header format and unpacks the data to get the name_len and filename
    if len(data) < 2:
        raise ValueError("Invalid upload payload")
    name_len = struct.unpack(">H", data[:2])[0]
    filename = data[2:2+name_len].decode('utf-8')
    return filename


def build_load_file_payload(filename: str) -> bytes:
    # format used is >H + filename in byte
    name_bytes = filename.encode('utf-8')
    return struct.pack(">H", len(name_bytes)) + name_bytes


def parse_load_file_payload(data: bytes) -> str:
    # parsing is exactly the same as the parse_upload_ppt_payload, >H + filename
    if len(data) < 2:
        raise ValueError("Invalid load payload")
    name_len = struct.unpack(">H", data[:2])[0]
    filename = data[2:2+name_len].decode('utf-8')
    return filename


def build_go_to_slide_payload(slide_num: int) -> bytes:
    # header format: [slide num]
    return struct.pack(">H", slide_num)


def parse_go_to_slide_payload(data: bytes) -> int:
    if len(data) < 2:
        raise ValueError("Invalid go_to_slide payload")
    return struct.unpack(">H", data[:2])[0]


def build_slide_count_response(count: int) -> bytes:
    return struct.pack(">H", count)


def parse_slide_count_response(data: bytes) -> int:
    if len(data) < 2:
        raise ValueError("Invalid slide_count response")
    return struct.unpack(">H", data[:2])[0]


def build_current_slide_response(slide_num: int) -> bytes:
    return struct.pack(">H", slide_num)


def parse_current_slide_response(data: bytes) -> int:
    if len(data) < 2:
        raise ValueError("Invalid current_slide response")
    return struct.unpack(">H", data[:2])[0]


def build_file_list_response(filenames: list) -> bytes:
    # Format: [2-byte count][filename1_len:filename1][filename2_len:filename2]...
    result = struct.pack(">H", len(filenames))
    for filename in filenames:
        name_bytes = filename.encode('utf-8')
        result += struct.pack(">H", len(name_bytes)) + name_bytes
    return result


def parse_file_list_response(data: bytes) -> list:
    if len(data) < 2:
        raise ValueError("Invalid file_list response")
    
    count = struct.unpack(">H", data[:2])[0]
    filenames = []
    offset = 2
    
    for _ in range(count):
        if offset + 2 > len(data):
            break
        name_len = struct.unpack(">H", data[offset:offset+2])[0]
        offset += 2
        
        filename = data[offset:offset+name_len].decode('utf-8')
        filenames.append(filename)
        offset += name_len
    
    return filenames


def build_slide_changed_response(slide_num: int) -> bytes:
    return struct.pack(">H", slide_num)


def build_presenter_info_response(presenter_name: str) -> bytes:
    name_bytes = presenter_name.encode('utf-8')
    return struct.pack(">H", len(name_bytes)) + name_bytes


def parse_presenter_info_response(data: bytes) -> str:
    if len(data) < 2:
        raise ValueError("Invalid presenter_info response")
    name_len = struct.unpack(">H", data[:2])[0]
    return data[2:2+name_len].decode('utf-8')


def build_presenter_role_payload(presenter_name: str) -> bytes:
    name_bytes = presenter_name.encode('utf-8')
    return struct.pack(">H", len(name_bytes)) + name_bytes


def build_join_presenter_payload(client_name: str) -> bytes:
    name_bytes = client_name.encode('utf-8')
    return struct.pack(">H", len(name_bytes)) + name_bytes


def parse_join_presenter_payload(data: bytes) -> str:
    # unpacks header to extract the join_presenter payload
    if len(data) < 2:
        raise ValueError("Invalid join_presenter payload")
    name_len = struct.unpack(">H", data[:2])[0]
    return data[2:2+name_len].decode('utf-8')

def build_slide_image_start(slide_num: int, total_bytes: int, total_chunks: int) -> bytes:
    # format: [slide_num][total_bytes][total_chunks], short int int
    return struct.pack(">HII", slide_num, total_bytes, total_chunks)

def parse_slide_image_start(data: bytes) -> tuple:
    # parse or unpacks the build_slide_image_start payload
    if len(data) < 8:
        raise ValueError("Invalid slide_image_start payload")
    slide_num, total_bytes, total_chunks = struct.unpack(">HII", data[:8])
    return slide_num, total_bytes, total_chunks

def build_slide_image_chunk(chunk_id: int, chunk_data: bytes) -> bytes:
    return struct.pack(">H", chunk_id) + chunk_data

def parse_slide_image_chunk(data: bytes) -> tuple:
    if len(data) < 2:
        raise ValueError("Invalid slide_image_chunk payload")
    chunk_id = struct.unpack(">H", data[:2])[0]
    chunk_data = data[2:]
    return chunk_id, chunk_data
