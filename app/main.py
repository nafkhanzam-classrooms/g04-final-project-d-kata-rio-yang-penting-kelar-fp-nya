# main entry for the system

from app.config.config import load_dotenv
from app.http.http_server import HTTPServer
from app.routes.pptsharing.pptsharing_route import register_ppt_routes

load_dotenv(__name__)

server = HTTPServer(port=8000)

# register_ppt_routes(server)
# register_testing_routes(server)

register_ppt_routes(server)

server.run()
