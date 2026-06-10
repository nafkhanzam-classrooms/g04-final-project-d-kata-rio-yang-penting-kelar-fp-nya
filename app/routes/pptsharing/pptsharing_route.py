from app.http.http_server import HTTPRequest, HTTPResponse, HTTPServer
from pathlib import Path
from functools import partial

from app.controllers.pptsharing.ppt_route_map import *

# list of all the endpoints for the PPT Sharing service
# POST   /api/ppt/upload              Upload a .pptx file (multipart/form-data, field "file")
# GET    /api/ppt/files               List uploaded .pptx files
# POST   /api/ppt/load                Load a previously-uploaded file  { "filename": "..." }
# GET    /api/ppt/slides/count        Total slide count of the loaded file
# GET    /api/ppt/slides/current      Current slide number (1-based)
# POST   /api/ppt/slides/goto         Go to a specific slide           { "slide": <int, 1-based> }
# POST   /api/ppt/slides/next         Advance to next slide
# POST   /api/ppt/slides/prev         Go back to previous slide
# GET    /api/ppt/slides/image        JPEG bytes for the current slide
# GET    /api/ppt/slides/:num/image   JPEG bytes for slide <num> (1-based)
# POST   /api/ppt/presenter/join      Claim presenter role             { "name": "..." }
# GET    /api/ppt/presenter           Current presenter info

def ensure_upload_dir_exists() -> Path:
    current_file = Path(__file__).resolve()
    project_root = current_file.parent.parent.parent.parent

    uploads_dir = project_root / "public" / "uploads"  # No leading slash
    uploads_dir.mkdir(parents=True, exist_ok=True)  # Create dir if missing

    return uploads_dir

UPLOAD_DIR: Path = ensure_upload_dir_exists()

def register_ppt_routes(server: HTTPServer) -> None:
    #Register all PPT-related routes on the given HTTPServer instance.
    # 
    #Call this from main.py after creating the server:
    # 
    #from app.ppt.ppt_routes import register_ppt_routes
    #register_ppt_routes(server)

    server.add_route("/api/ppt/upload",              "POST",  partial(handle_upload, upload_dir=UPLOAD_DIR))
    server.add_route("/api/ppt/files",               "GET",   partial(handle_list_files, upload_dir=UPLOAD_DIR))
    server.add_route("/api/ppt/load",                "POST",  partial(handle_load, upload_dir=UPLOAD_DIR))
    server.add_route("/api/ppt/slides/count",        "GET",   handle_slide_count)
    server.add_route("/api/ppt/slides/current",      "GET",   handle_get_current_slideno)
    server.add_route("/api/ppt/slides/goto",         "POST",  handle_goto_slide)
    server.add_route("/api/ppt/slides/next",         "POST",  handle_next_slide)
    server.add_route("/api/ppt/slides/prev",         "POST",  handle_prev_slide)
    server.add_route("/api/ppt/slides/image",        "GET",   handle_current_slide_image)
    server.add_route("/api/ppt/slides/:num/image",   "GET",   handle_slide_image_bynum)
    server.add_route("/api/ppt/presenter/join",      "POST",  handle_presenter_join)
    server.add_route("/api/ppt/presenter",           "GET",   handle_get_presenter)
 
    print("[PPT-ROUTES] Registered PPT routes.")

