# main entry for the system

from pathlib import Path
from app.config.config import load_dotenv
from app.http.http_server import HTTPServer
from app.routes.pptsharing.pptsharing_route import register_ppt_routes

load_dotenv(__name__)

def get_project_public_pathdir() -> Path:
    current_file = Path(__file__).resolve()
    public_root_dir = current_file.parent.parent / "public"

    return public_root_dir

PUBLIC_DIR: Path = get_project_public_pathdir()

print(f"PUBLIC_DIR: {PUBLIC_DIR}")

server = HTTPServer(port=8000, static_dir=PUBLIC_DIR)

# register_ppt_routes(server)
# register_testing_routes(server)

register_ppt_routes(server)

server.run()
