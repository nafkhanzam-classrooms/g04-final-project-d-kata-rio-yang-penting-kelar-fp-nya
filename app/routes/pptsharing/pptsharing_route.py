from app.http.http_server import HTTPResponse

def register_ppt_routes(server):

    @server.get("/")
    def home(request):
        return HTTPResponse.html(
            "<h1>PPT Sharing</h1>"
        )

    @server.get("/api/files")
    def list_files(request):
        return HTTPResponse.json(
            {
                "files": [
                    "presentation1.pptx",
                    "presentation2.pptx"
                ]
            }
        )

    @server.post("/api/next")
    def next_slide(request):
        return HTTPResponse.json(
            {"success": True}
        )
