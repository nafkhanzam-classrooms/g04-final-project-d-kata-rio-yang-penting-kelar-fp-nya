# main entry for the system

from app.config.config import add_env_manual, load_dotenv
from app.http.http_server import HTTPServer
# from app.http.pptsharing.pptsharing_route import register_ppt_routes
# from app.http.testing.testing_route import register_testing_routes

load_dotenv(__name__)
# add_env_manual("UPLOAD_PATH", __name__)

server = HTTPServer(port=8000)

# register_ppt_routes(server)
# register_testing_routes(server)

server.run()
