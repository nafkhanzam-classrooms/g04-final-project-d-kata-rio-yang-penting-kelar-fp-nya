import subprocess
import tempfile
import shutil

from typing import Optional
from pathlib import Path
import os

def util_convert_ppt_to_pptx(filepath: str) -> Optional[str]:
    # Convert a .ppt file to .pptx using LibreOffice. Returns the new path or None on failure."""
    try:
        print(f"[PPTProcessor] filepath: {filepath}")
        tmpdir = tempfile.mkdtemp()
        result = subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pptx", "--outdir", tmpdir, filepath],
            capture_output=True,
            timeout=60,
        )

        print(f"[PPTProcessor] LibreOffice stdout: {result.stdout.decode()}")
        print(f"[PPTProcessor] LibreOffice stderr: {result.stderr.decode()}")
        print(f"[PPTProcessor] LibreOffice returncode: {result.returncode}")

        if result.returncode != 0:
            return None
        
        basename = Path(filepath).stem + ".pptx"
        converted = os.path.join(tmpdir, basename)
        return converted if os.path.exists(converted) else None
    except Exception as exc:
        print(f"[PPTProcessor] .ppt conversion error: {exc}")
        return None
