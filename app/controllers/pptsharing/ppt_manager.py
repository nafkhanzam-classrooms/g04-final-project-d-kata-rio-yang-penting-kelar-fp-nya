import os
from typing import Dict, List, Optional, Tuple

import socket

from app.utils.packetheader import FramedMessage
from app.controllers.pptsharing.ppt_processor import PPTProcessor
from app.controllers.pptsharing.ppt_protocol import (
    TCPResponse,
    create_tcp_response,
    build_slide_changed_response,
    build_slide_image_start,
    build_slide_image_chunk,
    SLIDE_CHUNK_SIZE,
)

class PPTManager:
    CHUNK_SIZE: int = SLIDE_CHUNK_SIZE
    def __init__(self) -> None:
        self.current_file: Optional[str] = None
        self.current_slideno: int  = 0
        self.total_slides: int = 0
        self.presenter_fd: Optional[int] = None
        self.presenter_name: Optional[str] = None

        self.fd_to_socket: Dict[int, socket.socket] = {}

        self.viewer_fds: List[int] = []

        self.slide_cache = []

        self._processor = PPTProcessor()
        self.slide_cache: List[bytes] = []

    # register and unregister a client fd connected, also when the disconnected fd is the presenter_fd, resets the presenter_fd and name
    def register_client(self, fd: int, sock: socket.socket) -> None:
        self.fd_to_socket[fd] = sock

    def unregister_client(self, fd: int) -> None:
        self.fd_to_socket.pop(fd, None)
        if fd in self.viewer_fds:
            self.viewer_fds.remove(fd)
        if fd == self.presenter_fd:
            self.presenter_fd = None
            self.presenter_name = None

    # role management for setting presenter
    def set_presenter(self, presenter_fd: int, presenter_name: str) -> None:
        if presenter_fd is not None and self.presenter_fd != presenter_fd:
            if self.presenter_fd not in self.viewer_fds:
                self.viewer_fds.append(self.presenter_fd)

        self.presenter_fd = presenter_fd
        self.presenter_name = presenter_name

        if presenter_fd in self.viewer_fds:
            self.viewer_fds.remove(presenter_fd)

    # role management add viewer role
    def add_viewer(self, viewer_fd: int) -> None:
        if viewer_fd not in self.viewer_fds and viewer_fd != self.presenter_fd:
            self.viewer_fds.append(viewer_fd)

    # helper to check if the given fd is the presenter
    def is_presenter(self, fd: int) -> bool:
        return fd == self.presenter_fd


    # file loading utlity
    def load(self, ppt_path: str) -> Tuple[bool, Optional[Dict[str, object]]]:
        ok = self._processor.load_file(ppt_path)
        if not ok:
            return False, None

        self.current_file = ppt_path
        self.total_slides = self._processor.get_total_slides()
        self.current_slideno = 0
        self.slide_cache = list(self._processor.slide_cache or [])

        info: Dict[str, object] = {
            "file": os.path.basename(ppt_path),
            "total_slides": self.total_slides,
            "current_slide": self.current_slideno,
        }

        return True, info

    # jumps to slidenum
    def goto_slide(self, slide_num :int) -> bool:
        if not self._processor.loaded_file:
            return False

        ok = self._processor.goto_slide(slide_num)
        if ok:
            self.current_slideno = self._processor.get_current_slideno()
            self.broadcast_slidechange()
        return ok

    # when clicking the next slide or hitting the API next slide
    def next_slide(self) -> bool:
        if not self._processor.loaded_file:
            return False

        ok = self._processor.next()
        if ok:
            self.current_slideno = self._processor.get_current_slideno()
            self.broadcast_slidechange()
        return ok

    # when clicking the prev slide or htting the API prev slide
    def prev_slide(self) -> bool:
        if not self._processor.loaded_file:
            return False

        ok = self._processor.prev()
        if ok:
            self.current_slideno = self._processor.get_current_slideno()
            self.broadcast_slidechange()
        return ok
    
    # get current JPEG bytes from current slide no
    def get_current_slide_bytes(self) -> bytes:
        return self._processor.extract_slide(self.current_slideno)

    def get_slide_bytes(self, slide_num: int) -> bytes:
        return self._processor.extract_slide(slide_num)

    def broadcast_slidechange(self) -> None:
        slide_1based = self.current_slideno + 1
        notify_message = create_tcp_response(
            TCPResponse.SLIDE_CHANGED,
            build_slide_changed_response(slide_1based)
        )

    def send_slide_image_to(self, fd: int, slide_num: int) -> bool:
        if fd not in self.fd_to_socket:
            return False
        
        image_data = self._processor.extract_slide(slide_num)
        if not image_data:
            return False

        return True

    # internal helpers function
    def _send_to_all_viewers(self, data: bytes) -> None:
        dead = []
        for fd in list(self.viewer_fds):
            if not self._send_to_fd(fd, data):
                dead.append(fd)

        for fd in dead:
            self.unregister_client(fd)

    def _send_to_fd(self, fd: int, data: bytes) -> bool:
        sock = self.fd_to_socket.get(fd)
        if sock is None:
            return False

        try:
            sock.sendall(FramedMessage.frame(data))
            return True
        except (BrokenPipeError, OSError):
            return False

    def _stream_slide_image_to_viewers(self, slide_num: int, image_data: bytes) -> None:
        for fd in list(self.viewer_fds):
            self._stream_slide_image(fd, slide_num, image_data)
        
    def _stream_slide_image(self, fd: int, slide_num: int, image_data: bytes) -> None:
        chunk_size = self.CHUNK_SIZE
        total_bytes = len(image_data)
        total_chunks = (total_bytes + chunk_size - 1) // chunk_size
        slide_1based = slide_num + 1

        start_payload = build_slide_image_start(
            slide_1based, total_bytes, total_chunks
        )

        start_msg = create_tcp_response(
            TCPResponse.SLIDE_IMAGE_START, start_payload
        )

        if not self._send_to_fd(fd, start_msg):
            return

        for chunk_id in range(total_chunks):
            offset = chunk_size * chunk_id
            chunk_data = image_data[offset:offset + chunk_size]
            chunk_payload  = build_slide_image_chunk(chunk_id, chunk_data)
            chunk_msg = create_tcp_response(TCPResponse.SLIDE_IMAGE_CHUNK, chunk_payload)
            if not self._send_to_fd(fd, chunk_msg):
                return

        complete_msg = create_tcp_response(TCPResponse.SLIDE_IMAGE_COMPLETE)
        self._send_to_fd(fd, complete_msg)
        try:
            sock.sendall(FramedMessage.frame(data))
            return True
        except (BrokenPipeError, OSError):
            return False
