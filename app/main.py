# main entry for the system

from app.config.config import load_dotenv
from app.http.http_server import HTTPServer

load_dotenv(__name__)

server = HTTPServer(port=8000)

# register_ppt_routes(server)
# register_testing_routes(server)

server.run()
