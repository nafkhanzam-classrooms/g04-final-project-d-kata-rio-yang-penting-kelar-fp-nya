import json
from pathlib import Path
from typing import Dict, Any

from app.http.http_server import HTTPRequest, HTTPResponse
from app.model.user_model import user_model
from app.utils.code_evaluator import CodeEvaluator


class UserController:
    """
    HTTP REST controller for user operations.
    Also provides class methods callable from WebSocket dispatch.
    """

    QUESTIONS_DIR = Path(__file__).parent.parent.parent / "data" / "questions"
    DIFFICULTIES = ["easy", "medium", "hard"]

    @staticmethod
    def get_profile(request: HTTPRequest) -> HTTPResponse:
        """Return the profile for the currently authenticated user (stubbed to user1)."""
        # TODO: Extract username from HTTP Session once HTTP auth is implemented.
        user = user_model.get_user("user1")
        if not user:
            return HTTPResponse.json({"error": "User not found"}, 404)
        return HTTPResponse.json(user.to_dict())

    @staticmethod
    def get_leaderboard(request: HTTPRequest) -> HTTPResponse:
        """Return the global leaderboard."""
        return HTTPResponse.json(user_model.get_leaderboard())

    @classmethod
    def submit_code(cls, request: HTTPRequest) -> HTTPResponse:
        """
        HTTP REST endpoint for code submission.
        """
        try:
            content_type = request.headers.get("content-type", "")
            if "multipart/form-data" in content_type:
                data = request.form()
            else:
                data = json.loads(request.body)

            code = data.get("code")
            problem_id = data.get("problem_id")

            if not problem_id or not code:
                return HTTPResponse.json({"error": "Missing problem_id or code"}, 400)

            result = cls._evaluate_submission(code, problem_id, "user1")
            return HTTPResponse.json(result)

        except json.JSONDecodeError:
            return HTTPResponse.json({"error": "Invalid JSON body"}, 400)
        except Exception as e:
            return HTTPResponse.json({"error": str(e)}, 500)

    @classmethod
    def submit_code_ws(cls, code: str, problem_id: str, username: str = "user1") -> Dict[str, Any]:
        """
        WebSocket-callable code submission.
        Returns a dict directly (no HTTPResponse wrapper).
        """
        if not problem_id or not code:
            return {"status": "Error", "error": "Missing problem_id or code"}

        return cls._evaluate_submission(code, problem_id, username)

    @classmethod
    def _evaluate_submission(cls, code: str, problem_id: str, username: str) -> Dict[str, Any]:
        """Core submission logic shared between HTTP and WebSocket paths."""
        test_cases = []
        difficulty = "Medium"
        found = False

        for diff in cls.DIFFICULTIES:
            q_dir = cls.QUESTIONS_DIR / diff / problem_id
            if q_dir.is_dir():
                tc_file = q_dir / "test_cases.json"
                if tc_file.is_file():
                    with open(tc_file, "r", encoding="utf-8") as f:
                        test_cases = json.load(f)

                meta_file = q_dir / "metadata.json"
                if meta_file.is_file():
                    with open(meta_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        difficulty = meta.get("difficulty", diff.capitalize())

                found = True
                break

        if not found:
            return {"status": "Error", "error": "Question not found"}

        if not test_cases:
            return {"status": "Error", "error": "No test cases found for this question"}

        eval_result = CodeEvaluator.evaluate(code, test_cases)

        if eval_result.get("status") == "Accepted":
            streak_info = user_model.solve_problem(username, problem_id, difficulty)
            eval_result["user_stats"] = streak_info

        return eval_result
