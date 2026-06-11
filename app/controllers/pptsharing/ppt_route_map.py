from typing import Dict
from app.http.http_server import HTTPRequest, HTTPResponse, HTTPServer
from app.controllers.pptsharing.ppt_manager import PPTManager
import os
import json
from pathlib import Path

from app.utils.sanitize_filename import sanitize_filename

_manager = PPTManager()

# helper function to respond quickly if JSON is preferred
def json_ok(data: dict, status: int = 200) -> HTTPResponse:
    return HTTPResponse.json({"ok": True, **data}, status)

def json_error(message: str, status: int = 400) -> HTTPResponse:
    return HTTPResponse.json({"error": message}, status)

# handling upload using multipart/form-data that only accepts .pptx or .ppt
# POST /api/ppt/upload
def handle_upload(request: HTTPRequest, upload_dir: Path) -> HTTPResponse:
    files = request.files()
    if not files:
        return json_error("No file uploaded, Use multipart/form-data with field 'file'.")

    ppt_file = next(
        (f for f in files if f.filename.lower().endswith((".pptx", ".ppt"))),
        None,
    )

    if ppt_file is None:
        return json_error("Uploaded file must be a .pptx file")

    # safe renaming the file if contains any space, utilizing the sanitize_filename imported from util
    safe_name = sanitize_filename(ppt_file.filename)
    if not safe_name:
        return json_error("Invalid filename")

    # saves the ppt file into the upload_dir passed by the function argument
    dest = upload_dir / safe_name
    ppt_file.save(str(dest))

    return json_ok({"filename": safe_name, "size": len(ppt_file.data)}, 201)

# list all ppt or pptx file inside the public/uploads
# GET /api/ppt/files
def handle_list_files(request: HTTPRequest, upload_dir: Path) -> HTTPResponse:
    try:
        files = [
            f.name for f in upload_dir.iterdir() if f.suffix.lower() in ('.pptx', '.ppt')
        ]
        
        return HTTPResponse.json({"files" : sorted(files)})
    except Exception as exc:
        return json_error(str(exc), 500)

# handling when request is trying to load a ppt file that already uploaded
# and to be converted by the PPTManager

# POST /api/ppt/load
def handle_load(request: HTTPRequest, upload_dir: Path) -> HTTPResponse:
    try:
        body: Dict = request.json()
        filename: str = body.get("filename", "").strip()
    except Exception:
        return json_error("Body must be JSON with key 'filename'")

    if not filename:
        return json_error("'filename' is required")

    filepath = upload_dir / Path(filename).name
    if not filepath.exists():
        return json_error(f"File {filename} cannot be found", 404)
    
    ok, info = _manager.load(str(filepath))
    if not ok or info is None:
        return json_error("Failed to load presentation", 500)

    return json_ok(info)

# returns the total slides from the loaded PPT
# GET /api/ppt/slides/count
def handle_slide_count(request: HTTPRequest) -> HTTPResponse:
    if not _manager.current_file:
        return json_error("No presentation file loaded", 404)

    return HTTPResponse.json({"total_slides": _manager.total_slides})

# returns the current slide no. in the PPTManager
# GET /api/ppt/slides/current
def handle_get_current_slideno(request: HTTPRequest) -> HTTPResponse:
    if not _manager.current_file:
        return json_error("No presentation file loaded", 404)

    return HTTPResponse.json({"slide": _manager.current_slideno + 1})

# handler for changing the slide no to a number
# POST /api/ppt/slides/goto
def handle_goto_slide(request: HTTPRequest) -> HTTPResponse:
    if not _manager.current_file:
        return json_error("No presentation file loaded", 404)
    
    try:
        body: Dict = request.json()
        slide: int = int(body.get("slide", 0))
    except Exception:
        return json_error("Body must contain JSON with 'slide' key")

    if slide < 1 or slide > _manager.total_slides:
        return json_error(f"Slide number is invaild! {slide}/{_manager.total_slides}")

    ok = _manager.goto_slide(slide - 1) # convert to 0-based
    if not ok:
        return json_error(f"Failed to navigate to slide no. {slide}", 500)
    
    return json_ok({"slide": _manager.current_slideno + 1})

# handler for changing the slide no to the next
# POST /api/ppt/slides/next
def handle_next_slide(request: HTTPRequest) -> HTTPResponse:
    if not _manager.current_file:
        return json_error("No presentation file loaded", 404)

    ok = _manager.next_slide()
    if not ok:
        return json_error("Already on the last slide", 400)

    return json_ok({"slide": _manager.current_slideno + 1})

# handler for changing the slide no to the previous
# POST /api/ppt/slides/prev
def handle_prev_slide(request: HTTPRequest) -> HTTPResponse:
    if not _manager.current_file:
        return json_error("No presentation file loaded", 404)

    ok = _manager.prev_slide()
    if not ok:
        return json_error("Already on the first slide", 400)

    return json_ok({"slide": _manager.current_slideno + 1})

# jhandler for transmitting the image slide to the client / presenter
# GET /api/ppt/slides/image
def handle_current_slide_image(request: HTTPRequest) -> HTTPResponse:
    if not _manager.current_file:
        return json_error("No presentation file loaded", 404)

    data = _manager.get_current_slide_bytes()
    if not data:
        return json_error("Slide image not available", 500)

    return HTTPResponse(200, data, "image/jpeg")

# handler for transmitting image slide but custom slide number to client / presenter
# GET /api/ppt/slides/:num/image, :num is passed down into the request parameter
def handle_slide_image_bynum(request: HTTPRequest, num: str) -> HTTPResponse:
    if not _manager.current_file:
        return json_error("No presentation file loaded", 404)

    try:
        slide_1based = int(num)
    except ValueError:
        return json_error("Slide number must be an integer")

    if slide_1based < 1 or slide_1based > _manager.total_slides:
        return json_error(f"Slide number is not valid {slide_1based}/{_manager.total_slides}", 404)

    data = _manager.get_slide_bytes(slide_1based - 1)
    if not data:
        return json_error("Slide image not available", 500)

    return HTTPResponse(200, data, "image/jpeg")

# sets the presenter name and file descriptor (addr or ID)
# POST /api/ppt/presenter/join
def handle_presenter_join(request: HTTPRequest) -> HTTPResponse:
    try:
        body: Dict = request.json()
        name: str = body.get("name", "").strip()
    except Exception:
        return json_error("Body must be JSON with 'name' key exists")

    if not name:
        return json_error("'name' is required")

    client_addr = getattr(request, "client_addr", None) or ("unknown", 0)
    synthetic_fd = hash(client_addr) & 0xFFFF

    _manager.set_presenter(synthetic_fd, name)
    return json_ok({"presenter": name})

# get the name of the presenter
# /api/ppt/presenter
def handle_get_presenter(request: HTTPRequest) -> HTTPResponse:
    if _manager.presenter_name:
        return HTTPResponse.json({"presenter": _manager.presenter_name})

    return HTTPResponse.json({"presenter": None})

def handle_get_presentation_filename(request: HTTPRequest) -> HTTPResponse:
    if not _manager.current_file:
        return json_error("No presentation file loaded", 404)

    return json_ok({"ppt_name": _manager.current_file})
