import sys
import logging
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from app.http.http_server import CodEduServer, HTTPRequest, HTTPResponse, logging_middleware
from app.controllers.user_controller import UserController
from app.controllers.question_controller import QuestionController

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

public_dir = root_dir / "public"
server = CodEduServer(port=8080, static_dir=public_dir)
server.use_middleware(logging_middleware)

@server.get("/")
def index(request: HTTPRequest) -> HTTPResponse:
    request.path = "/index.html"
    return server.serve_static(request)

server.add_route("/api/user", "GET", UserController.get_profile)
server.add_route("/api/submit", "POST", UserController.submit_code)
server.add_route("/api/leaderboard", "GET", UserController.get_leaderboard)

server.add_route("/api/questions", "GET", QuestionController.get_all_questions)
server.add_route("/api/questions/:question_id", "GET", QuestionController.get_question)

server.add_static_route("/css")
server.add_static_route("/js")

if __name__ == "__main__":
    server.run()
