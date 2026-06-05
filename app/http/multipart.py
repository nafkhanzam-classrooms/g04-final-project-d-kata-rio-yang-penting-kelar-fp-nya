class MultipartFile:
    def __init__(
        self,
        field_names: str,
        filename: str,
        content_type: str,
        data: bytes
    ) -> None:
        self.field_names = field_names
        self.filename = filename
        self.content_type = content_type
        self.data = data

    def save(self, path: str):
        with open(path, "wb") as f:
            f.write(self.data)
