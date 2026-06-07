import struct
import hashlib
import base64
import logging
from typing import Optional, Tuple, Dict, List, Any
from enum import IntEnum

logger = logging.getLogger(__name__)

WEBSOCKET_MAGIC_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_FRAME_SIZE = 10 * 1024 * 1024
MAX_HEADER_SIZE = 8192


class WSOpcode(IntEnum):
    """WebSocket frame opcodes (RFC 6455 §5.2)"""
    CONTINUATION = 0x0
    TEXT = 0x1
    BINARY = 0x2
    CLOSE = 0x8
    PING = 0x9
    PONG = 0xA


class WSCloseCode(IntEnum):
    """WebSocket close status codes (RFC 6455 §7.4.1)"""
    NORMAL = 1000
    GOING_AWAY = 1001
    PROTOCOL_ERROR = 1002
    UNSUPPORTED_DATA = 1003
    NO_STATUS = 1005
    ABNORMAL = 1006
    INVALID_PAYLOAD = 1007
    POLICY_VIOLATION = 1008
    MESSAGE_TOO_BIG = 1009
    MANDATORY_EXTENSION = 1010
    INTERNAL_ERROR = 1011


class WebSocketHandshake:
    """Handles the HTTP → WebSocket upgrade handshake."""

    @staticmethod
    def is_websocket_upgrade(headers: Dict[str, str]) -> bool:
        return (
            headers.get("upgrade", "").lower() == "websocket"
            and "upgrade" in headers.get("connection", "").lower()
            and headers.get("sec-websocket-version", "") == "13"
            and len(headers.get("sec-websocket-key", "")) > 0
        )

    @staticmethod
    def compute_accept_key(websocket_key: str) -> str:
        combined = websocket_key.strip() + WEBSOCKET_MAGIC_GUID
        sha1_hash = hashlib.sha1(combined.encode("utf-8")).digest()
        return base64.b64encode(sha1_hash).decode("utf-8")

    @staticmethod
    def build_accept_response(websocket_key: str, extra_headers: Optional[Dict[str, str]] = None) -> bytes:
        accept_key = WebSocketHandshake.compute_accept_key(websocket_key)

        lines = [
            "HTTP/1.1 101 Switching Protocols",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Accept: {accept_key}",
            "Server: CodEdu/1.0",
        ]

        if extra_headers:
            lines.extend(f"{key}: {value}" for key, value in extra_headers.items())

        return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")

    @staticmethod
    def build_reject_response(status: int = 400, reason: str = "Bad Request") -> bytes:
        body = f"WebSocket handshake failed: {reason}"
        return (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: text/plain\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
            f"{body}"
        ).encode("utf-8")


class WebSocketFrame:
    """WebSocket frame parser and builder (RFC 6455)."""

    @staticmethod
    def parse(buffer: bytes) -> Tuple[Optional[Dict[str, Any]], int]:
        buf_len = len(buffer)
        if buf_len < 2:
            return None, 0

        byte0, byte1 = buffer[0], buffer[1]

        fin = bool(byte0 & 0x80)
        rsv_any = bool(byte0 & 0x70)

        if rsv_any:
            raise ValueError("RSV bits must be 0")

        opcode = byte0 & 0x0F
        masked = bool(byte1 & 0x80)
        payload_len = byte1 & 0x7F

        if opcode not in {0x0, 0x1, 0x2, 0x8, 0x9, 0xA}:
            raise ValueError(f"Unknown opcode: {opcode:#x}")

        if opcode >= 0x8:
            if not fin:
                raise ValueError("Control frames must not be fragmented")
            if payload_len > 125:
                raise ValueError("Control frame payload too large")

        offset = 2

        if payload_len == 126:
            if buf_len < offset + 2:
                return None, 0
            payload_len = struct.unpack("!H", buffer[offset:offset + 2])[0]
            offset += 2
        elif payload_len == 127:
            if buf_len < offset + 8:
                return None, 0
            payload_len = struct.unpack("!Q", buffer[offset:offset + 8])[0]
            offset += 8
            if payload_len >> 63:
                raise ValueError("Payload length MSB must be 0")

        if payload_len > MAX_FRAME_SIZE:
            raise ValueError(f"Frame payload too large: {payload_len} bytes")

        mask_key = None
        if masked:
            if buf_len < offset + 4:
                return None, 0
            mask_key = buffer[offset:offset + 4]
            offset += 4

        if buf_len < offset + payload_len:
            return None, 0

        payload = bytearray(buffer[offset:offset + payload_len])

        if masked and mask_key:
            WebSocketFrame._apply_mask(payload, mask_key)

        return {
            "fin": fin,
            "opcode": WSOpcode(opcode),
            "payload": bytes(payload),
        }, offset + payload_len

    @staticmethod
    def _apply_mask(data: bytearray, mask_key: bytes) -> None:
        mask_len = len(mask_key)
        for i in range(len(data)):
            data[i] ^= mask_key[i % mask_len]

    @staticmethod
    def build(payload: bytes, opcode: WSOpcode = WSOpcode.TEXT, fin: bool = True) -> bytes:
        frame = bytearray()
        frame.append((0x80 if fin else 0x00) | (opcode & 0x0F))

        payload_len = len(payload)
        if payload_len <= 125:
            frame.append(payload_len)
        elif payload_len <= 65535:
            frame.append(126)
            frame.extend(struct.pack("!H", payload_len))
        else:
            frame.append(127)
            frame.extend(struct.pack("!Q", payload_len))

        frame.extend(payload)
        return bytes(frame)

    @staticmethod
    def build_text(text: str) -> bytes:
        return WebSocketFrame.build(text.encode("utf-8"), WSOpcode.TEXT)

    @staticmethod
    def build_close(code: WSCloseCode = WSCloseCode.NORMAL, reason: str = "") -> bytes:
        payload = struct.pack("!H", code)
        if reason:
            payload += reason.encode("utf-8")[:123]
        return WebSocketFrame.build(payload, WSOpcode.CLOSE)

    @staticmethod
    def build_ping(data: bytes = b"") -> bytes:
        return WebSocketFrame.build(data[:125], WSOpcode.PING)

    @staticmethod
    def build_pong(data: bytes = b"") -> bytes:
        return WebSocketFrame.build(data[:125], WSOpcode.PONG)


class WebSocketConnection:
    """Per-connection state for a WebSocket client."""

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.buffer = bytearray()
        self.handshake_complete = False

        self._fragment_opcode: Optional[WSOpcode] = None
        self._fragment_buffer = bytearray()

        self.session_token: Optional[str] = None
        self.username: Optional[str] = None
        self.authenticated = False

        self.last_pong_time = 0.0
        self.ping_pending = False

    def feed(self, data: bytes) -> None:
        self.buffer.extend(data)
        if len(self.buffer) > MAX_FRAME_SIZE + 14:
            raise ValueError("WebSocket buffer overflow")

    def parse_frames(self) -> List[Dict[str, Any]]:
        messages = []

        while True:
            try:
                frame, consumed = WebSocketFrame.parse(bytes(self.buffer))
            except ValueError as e:
                logger.warning(f"[WS] Frame parse error on fd {self.fd}: {e}")
                raise

            if frame is None:
                break

            self.buffer = self.buffer[consumed:]

            opcode = frame["opcode"]
            payload = frame["payload"]
            fin = frame["fin"]

            if opcode in {WSOpcode.CLOSE, WSOpcode.PING, WSOpcode.PONG}:
                messages.append({"opcode": opcode, "payload": payload})
                continue

            if opcode in {WSOpcode.TEXT, WSOpcode.BINARY}:
                if self._fragment_opcode is not None:
                    raise ValueError("New data frame received during fragmentation")

                if fin:
                    messages.append({"opcode": opcode, "payload": payload})
                else:
                    self._fragment_opcode = opcode
                    self._fragment_buffer = bytearray(payload)

            elif opcode == WSOpcode.CONTINUATION:
                if self._fragment_opcode is None:
                    raise ValueError("Continuation frame without initial frame")

                self._fragment_buffer.extend(payload)

                if fin:
                    messages.append({
                        "opcode": self._fragment_opcode,
                        "payload": bytes(self._fragment_buffer),
                    })
                    self._fragment_opcode = None
                    self._fragment_buffer = bytearray()

        return messages

    def reset(self) -> None:
        self.buffer = bytearray()
        self._fragment_opcode = None
        self._fragment_buffer = bytearray()
        self.handshake_complete = False
        self.authenticated = False
