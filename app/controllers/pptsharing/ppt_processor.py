from typing import Dict, List, Optional, Tuple

class PPTProcessor:
    def __init__(self) -> None:
        self.loaded_file: Optional[str] = None
        self.total_slides: int = 0
        self.current_slide: int = 0
        self.slide_cache: Optional[List[bytes]] = []
        
        
    def load_file(self, filepath: str) -> bool:
        return True

    def extract_slide(self, slide_num: int) -> bytes:
        return b""

    def get_total_slides(self) -> int:
        return self.total_slides

    def get_current_slideno(self) -> int:
        return self.current_slide

    def next(self) -> bool:
        return True
    
    def prev(self) -> bool:
        return True

    def goto_slide(self, slideno: int) -> bool:
        return True
