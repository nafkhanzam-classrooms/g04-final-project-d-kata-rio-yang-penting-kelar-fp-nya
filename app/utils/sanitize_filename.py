from pathlib import Path
import re

def sanitize_filename(filename: str) -> str:
    # Replace spaces and special chars with underscores
    name = Path(filename).stem
    ext  = Path(filename).suffix
    name = re.sub(r"[^\w\-.]", "_", name)
    return name + ext
