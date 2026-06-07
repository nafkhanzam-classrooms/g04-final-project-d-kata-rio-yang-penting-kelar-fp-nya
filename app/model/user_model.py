import datetime
from typing import Optional, Set, Dict, List, Any


class User:
    """User model with gamification fields."""

    POINTS_MAP: Dict[str, int] = {
        "Easy": 100,
        "Medium": 200,
        "Hard": 300,
    }

    def __init__(self, username: str) -> None:
        self.username: str = username
        self.streak: int = 0
        self.last_solved_date: Optional[str] = None
        self.solved_problems: Set[str] = set()
        self.points: int = 0
        self.rank: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "username": self.username,
            "streak": self.streak,
            "points": self.points,
            "rank": self.rank,
            "solved_problems": list(self.solved_problems),
            "last_solved_date": self.last_solved_date,
        }

    def to_leaderboard_entry(self) -> Dict[str, Any]:
        return {
            "username": self.username,
            "points": self.points,
            "streak": self.streak,
            "solved_count": len(self.solved_problems),
            "rank": self.rank,
        }


class UserModel:
    """
    In-memory user store with gamification logic.
    The DB team will replace this with a real persistence layer.
    """

    def __init__(self) -> None:
        self.users: Dict[str, User] = {
            "user1": User("user1"),
        }

    def get_user(self, username: str) -> Optional[User]:
        return self.users.get(username)

    def get_or_create_user(self, username: str) -> User:
        """Get existing user or create a new one."""
        if username not in self.users:
            self.users[username] = User(username)
        return self.users[username]

    def solve_problem(self, username: str, problem_id: str, difficulty: str = "Medium") -> Dict[str, Any]:
        """Record a problem solve and calculate points + streak."""
        user = self.users.get(username)
        if not user:
            return {"success": False, "message": "User not found"}

        today = datetime.date.today().isoformat()
        streak_bonus = False
        points_earned = 0

        if problem_id not in user.solved_problems:
            user.solved_problems.add(problem_id)

            base_points = User.POINTS_MAP.get(difficulty, 200)

            if user.last_solved_date != today:
                yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
                if user.last_solved_date == yesterday:
                    user.streak += 1
                else:
                    user.streak = 1

                user.last_solved_date = today
                streak_bonus = True

            multiplier = min(2.0, 1.0 + user.streak * 0.1)
            points_earned = int(base_points * multiplier)
            user.points += points_earned

            self._recalculate_ranks()

        return {
            "success": True,
            "streak_bonus": streak_bonus,
            "current_streak": user.streak,
            "points_earned": points_earned,
            "total_points": user.points,
            "rank": user.rank,
            "multiplier": round(min(2.0, 1.0 + user.streak * 0.1), 1),
        }

    def get_leaderboard(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return sorted leaderboard entries."""
        self._recalculate_ranks()
        sorted_users = sorted(self.users.values(), key=lambda u: u.points, reverse=True)
        return [u.to_leaderboard_entry() for u in sorted_users[:limit]]

    def _recalculate_ranks(self) -> None:
        """Recalculate rank for all users based on points."""
        sorted_users = sorted(self.users.values(), key=lambda u: u.points, reverse=True)
        for i, user in enumerate(sorted_users, start=1):
            user.rank = i


# Singleton instance
user_model = UserModel()
