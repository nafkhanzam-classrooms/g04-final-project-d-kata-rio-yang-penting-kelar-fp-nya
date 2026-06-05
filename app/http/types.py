from enum import Enum

class HTTPMethod(Enum):
    # HTTP Methods as Enumeration (Lookup Table)
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    OPTIONS = "OPTIONS"
    HEAD = "HEAD"
    UNKNOWN = "UNKNOWN"
