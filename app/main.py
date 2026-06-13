# main entry for the system

# import os
import os
from pathlib import Path
from app.config.config import load_env_file
from app.http.http_server import HTTPServer
from app.routes.pptsharing.pptsharing_route import register_ppt_routes
from app.config.db.connection import Database

# print(f"{str(Path(__file__).parent.parent.resolve())}")
load_env_file(str(Path(__file__).parent.parent.resolve()))

def get_project_public_pathdir() -> Path:
    current_file = Path(__file__).resolve()
    public_root_dir = current_file.parent.parent / "public"

    return public_root_dir

PUBLIC_DIR: Path = get_project_public_pathdir()

db = Database.from_env()
db.load_schema(str((Path(__file__).parent / "config" / "db" / "schema.sql").resolve()))

print(f"PUBLIC_DIR: {PUBLIC_DIR}")

server = HTTPServer(port=int(os.environ.get("APP_PORT", "8000")), static_dir=PUBLIC_DIR)

# register_ppt_routes(server)
# register_testing_routes(server)

register_ppt_routes(server)

server.run()
