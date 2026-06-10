from typing import cast, Dict, List, Optional, Tuple
import os
import io

from pptx import Presentation as open_presentation
from pptx.presentation import Presentation
from pptx.util import Inches
from pptx.util import Pt
from pptx.util import Pt
from pptx.text.text import TextFrame
from pptx.dml.color import RGBColor
from pptx.shapes.base import BaseShape
from pptx.shapes.shapetree import SlideShapes
from pptx.shapes.autoshape import Shape
from PIL import Image
from PIL import ImageDraw, ImageFont

try:
    import subprocess
    _HAS_LIBREOFFICE = (
        subprocess.run(["which", "libreoffice"], capture_output=True)
    ).returncode == 0
except Exception:
    _HAS_LIBREOFFICE = False

RENDER_QUALITY: int = 85
DEFAULT_WIDTH: int = 1280
DEFAULT_HEIGHT: int = 720

class PPTProcessor:
    def __init__(self) -> None:
        self.loaded_file: Optional[str] = None
        self.total_slides: int = 0
        self.current_slide: int = 0
        self.slide_cache: Optional[List[bytes]] = []
        
        
    def load_file(self, filepath: str) -> bool:
        try:
            if not os.path.isfile(filepath):
                print(f"[PPTProcessor] File not found: {filepath}")
                return False

            prs: Presentation = open_presentation(filepath)
            self.total_slides = len(prs.slides)
            self.current_slide = 0
            self.loaded_file = filepath
            self.slide_cache = []

            for idx in range(self.total_slides):
                jpeg_bytes = self._render_slide(prs=prs, slide_idx=idx)
                self.slide_cache.append(jpeg_bytes)


            print(
                f"[PPTProcessor] Loaded '{filepath}' "
                f"({self.total_slides} slides)"
            )
            return True
        except Exception as exc:
            print(f"[PPTProcessor] load_file error: {exc}")
            self.loaded_file = None
            self.total_slides = 0
            self.slide_cache = []
            return False


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

    def _render_slide(self, prs: Presentation, slide_idx: int) -> bytes:
        if _HAS_LIBREOFFICE and self.loaded_file:
            result = self._render_via_libreoffice(slide_idx)
            if result:
                return result

        return self._render_slide(prs=prs, slide_idx=slide_idx)

    def _render_via_libreoffice(self, slide_idx: int) -> Optional[bytes]:
        import subprocess
        import tempfile
        import glob

        if self.loaded_file is None:
            return None

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                result = (
                    subprocess.run(
                        ["libreoffice", "--headless", "--convert-to", "png", "--outdir", tmpdir, self.loaded_file], 
                        capture_output=True, 
                        timeout=60
                    )
                )

                if result.returncode != 0:
                    return None

                pattern = os.path.join(tmpdir, "*.png")
                pages = sorted(glob.glob(pattern))

                if slide_idx >= len(pages):
                    return None

                img = Image.open(pages[slide_idx]).convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=RENDER_QUALITY)
                return buf.getvalue()
        except Exception as exc:
            print(f"[PPTProcessor] Libreoffice render error: {exc}")
            return None


    def _render_python_fallback(self, prs: Presentation, slide_idx: int) -> bytes:
        slide = prs.slides[slide_idx]

        w_emu: int = 0
        h_emu: int = 0

        try:
            w_emu: int = int(prs.slide_width  or 9144000)
            h_emu: int = int(prs.slide_height or 5143500)

            # 914400 is the EMUs per inch2
            scale = DEFAULT_WIDTH / (w_emu / 914400 * 96)
            width = DEFAULT_WIDTH
            height = int((h_emu / 914400 * 96) * scale)
        except Exception:
            width, height = DEFAULT_WIDTH, DEFAULT_HEIGHT

        bg_color = (255,255,255)
        try:
            bg = slide.background
            fill = bg.fill
            if fill.type is not None:
                from pptx.util import Pt
                from pptx.dml.color import RGBColor

                fg = fill.fore_color
                rgb = fg.rgb
                bg_color = (rgb[0], rgb[1], rgb[2])
        except Exception:
            pass

        img = Image.new("RGB", (width, height), bg_color)

        try:
            draw = ImageDraw.Draw(img)
            try:
                font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
                font_body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)

            except Exception:
                font_title = ImageFont.load_default()
                font_body = ImageFont.load_default()

            for base_shape in slide.shapes:
                if not base_shape.has_text_frame:
                    continue

                try:
                    x = int(base_shape.left / w_emu * width)
                    y = int(base_shape.top / h_emu * height)
                    sw = int(base_shape.width / w_emu * width)
                except Exception:
                    x, y, sw = 20, 20, width - 40

                cursor_y = y

                shape = cast(Shape, base_shape)
                text_frame = shape.text_frame
                for para_idx, para in enumerate(text_frame.paragraphs):
                    line = para.text.strip()

                    if not line:
                        cursor_y += 12
                        continue

                    font = font_title if para_idx == 0 else font_body
                    color = (30,30,30) # dark grey

                    try:
                        run = para.runs[0]
                        rgb = run.font.color.rgb
                        color = tuple(rgb) # red. green, blue
                    except Exception:
                        pass

                    draw.text((x + 8, cursor_y), line, fill=color, font=font)
                    try:
                        bbox = font.getbbox(line)
                        line_height = (bbox[3] - bbox[1]) + 6
                    except Exception:
                        line_height = 30

                    cursor_y += line_height
        except Exception as exc:
            print(f"[PPTProcessor] Text render error on slide {slide_idx}: {exc}")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=RENDER_QUALITY)
        return buf.getvalue()
