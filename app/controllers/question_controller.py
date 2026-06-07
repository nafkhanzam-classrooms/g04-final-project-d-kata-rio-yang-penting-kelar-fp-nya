import json
from pathlib import Path
from typing import List, Dict, Any

from app.http.http_server import HTTPRequest, HTTPResponse


class QuestionController:
    """HTTP REST controller for coding questions."""

    QUESTIONS_DIR = Path(__file__).parent.parent.parent / "data" / "questions"
    DIFFICULTIES = ["easy", "medium", "hard"]

    @classmethod
    def get_all_questions(cls, request: HTTPRequest) -> HTTPResponse:
        """Fetch metadata for all available questions."""
        questions: List[Dict[str, Any]] = []

        if not cls.QUESTIONS_DIR.exists():
            return HTTPResponse.json({"error": "Questions directory not found"}, 404)

        for difficulty in cls.DIFFICULTIES:
            diff_dir = cls.QUESTIONS_DIR / difficulty
            if not diff_dir.exists():
                continue

            for q_dir in diff_dir.iterdir():
                if q_dir.is_dir():
                    meta_file = q_dir / "metadata.json"
                    if meta_file.is_file():
                        try:
                            with open(meta_file, "r", encoding="utf-8") as f:
                                meta = json.load(f)
                                questions.append(meta)
                        except json.JSONDecodeError:
                            continue

        return HTTPResponse.json(questions)

    @classmethod
    def get_question(cls, request: HTTPRequest, question_id: str) -> HTTPResponse:
        """Fetch detailed data and description for a specific question."""
        for difficulty in cls.DIFFICULTIES:
            q_dir = cls.QUESTIONS_DIR / difficulty / question_id
            if q_dir.is_dir():
                meta_file = q_dir / "metadata.json"
                desc_file = q_dir / "description.md"

                if not meta_file.is_file():
                    continue

                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except json.JSONDecodeError:
                    return HTTPResponse.json({"error": "Invalid metadata"}, 500)

                if desc_file.is_file():
                    with open(desc_file, "r", encoding="utf-8") as f:
                        data["description"] = f.read()

                return HTTPResponse.json(data)

        return HTTPResponse.json({"error": "Question not found"}, 404)
