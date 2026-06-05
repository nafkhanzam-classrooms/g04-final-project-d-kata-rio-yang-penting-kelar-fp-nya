from typing import Dict, List, Optional, Tuple

class PPTManager:
    def __init__(self) -> None:
        self.current_file: Optional[str] = None
        self.current_slideno: int  = 0
        self.total_slides: int = 0
        self.presenter_fd: Optional[int] = None
        self.presenter_name: Optional[str] = None

        self.slide_cache = []

    def load(self, ppt_path: str) -> Tuple[bool, Optional[Dict[str, List[str]]]]:
        return False, None

    def goto_slide(self, slide_num:int) -> bool:
        return True

    def next_slide(self) -> bool:
        return True

    def prev_slide(self) -> bool:
        return True
    
    def get_current_slide_bytes(self) -> bytes:
        return b""

    def set_presenter(self, presenter_fd: int, presenter_name: str) -> None:
        self.presenter_name = presenter_name
        self.presenter_fd = presenter_fd

    def broadcast_slidechange(self) -> None:
        return
