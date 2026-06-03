from typing import Callable, List, Dict, Tuple, Optional
from app.http.types import HTTPMethod

class Route:
    def __init__(
            self, 
            path: str, 
            method: HTTPMethod, 
            handler: Callable, 
            is_pattern: bool = False) -> None:
        self.path = path
        self.method: HTTPMethod = method
        self.handler = handler
        self.is_pattern = is_pattern

    def matches(self, path: str, method: HTTPMethod) -> Tuple[bool, Dict[str, str]]:
        if self.method != method:
            return False, {}

        if not self.is_pattern:
            return self.path == path, {}

        pattern_parts = self.path.split('/')
        path_parts = path.split('/')

        if len(pattern_parts) != len(path_parts):
            return False, {}

        params = {}
        for pattern_part, path_part in zip(pattern_parts, path_parts):
            if pattern_part.startswith(':'):
                params[pattern_part[1:]] = path_part
            elif pattern_part != path_part:
                return False, {}

        return True, params
        
class Router:
    def __init__(self) -> None:
        self.routes: List[Route] = []

    def add_route(self, path: str, method: HTTPMethod, handler: Callable):
        self.routes.append(
            Route(path=path, method=method, handler=handler, is_pattern=":" in path)
        )

    def find_handler(self, path: str, method: HTTPMethod) -> Tuple[Optional[Callable], Dict[str,str]]:
        for route in self.routes:
            matches, params = route.matches(path, method)
            if matches:
                return route.handler, params
            
        return None, {}
