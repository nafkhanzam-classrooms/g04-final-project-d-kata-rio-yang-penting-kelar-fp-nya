# usage
#     from app.db.connection import Database
#     from app.models.user import UserRepository
#
#     db   = Database.from_env()
#     repo = UserRepository(db)
#
#     user = repo.get_by_username("alice")
#     if repo.has_permission(user["id"], "ppt.control"):
#         ...

from typing import Any, Dict, List, Optional

from app.config.db.connection import Database

# raw SQL data access for users, roles and permissions
class UserRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # user basic CRUD operations

    # returns username, name, email, is_active, created_at based on the ID
    def get_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one(
            "SELECT id, username, name, email, is_active, created_at FROM users WHERE id = %s",
            (user_id,),
        )

    # returns username, email, password_hash based on the username
    def get_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one(
            "SELECT id, username, name, email, password_hash, is_active FROM users WHERE username = %s",
            (username,),
        )

    # creates a user with providing the username, name, email, pw hash
    def create(self, username: str, name: str, email: str, password_hash: str) -> int:
        viewer = self.db.fetch_one(
            "SELECT id FROM role WHERE name = 'viewer'"
        )

        if viewer is None:
            raise ValueError("Viewer role not found")

        return self.db.execute(
            "INSERT INTO users (username, name, email, password_hash, role_id) VALUES (%s, %s, %s, %s, %s)",
            (username, name, email, password_hash, int(viewer["id"])),
        )

    # set a user to active with this ID
    def set_active(self, user_id: int, is_active: bool) -> None:
        self.db.execute(
            "UPDATE users SET is_active = %s WHERE id = %s",
            (is_active, user_id),
        )

    # delete a user based on the user ID
    def delete(self, user_id: int) -> None:
        self.db.execute("DELETE FROM users WHERE id = %s", (user_id,))

    # get what role a user has, intentionally only one role per user
    def get_role_for_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one(
            """
            SELECT r.id, r.name, r.description
            FROM role r
            JOIN users s ON s.role_id = r.id
            WHERE s.id = %s
            LIMIT 1
            """,
            (user_id,),
        )

    # assign a role on a user using UPDATE
    def assign_role(self, user_id: int, role_name: str) -> None:
        role = self.db.fetch_one("SELECT id FROM role WHERE name = %s", (role_name,))
        if role is None:
            raise ValueError(f"Role '{role_name}' does not exist")

        self.db.execute(
            """
            UPDATE users SET role_id = %s WHERE id = %s
            """,
            (int(role["id"]), user_id),
        )

    # remove role and assign a default role of viewer
    def remove_role(self, user_id: int) -> None:
        self.db.execute(
            """
            UPDATE users SET role_id = (SELECT id FROM role WHERE name = 'viewer') WHERE id = %s
            """,
            (user_id,),
        )

    # fetch permissions from a user
    def get_permissions_for_user(self, user_id: int) -> List[str]:
        rows = self.db.fetch_all(
            """
            SELECT DISTINCT p.code
            FROM permissions p
            JOIN role_permissions rp ON rp.permissions_id = p.id
            JOIN users us ON us.role_id = rp.role_id
            WHERE us.id = %s
            """,
            (user_id,),
        )
        return [row["code"] for row in rows]

    # check if a user has the permission code
    def has_permission(self, user_id: int, permission_code: str) -> bool:
        row = self.db.fetch_one(
            """
            SELECT 1
            FROM permissions p
            JOIN role_permissions rp ON rp.permissions_id = p.id
            JOIN users us ON us.role_id = rp.role_id
            WHERE us.id = %s AND p.code = %s
            LIMIT 1
            """,
            (user_id, permission_code),
        )
        return row is not None

    # check if a user having this role or not
    def has_role(self, user_id: int, role_name: str) -> bool:
        row = self.db.fetch_one(
            """
            SELECT 1
            FROM users us
            JOIN role r ON us.role_id = r.id
            WHERE us.id = %s AND r.name = %s
            LIMIT 1
            """,
            (user_id, role_name),
        )
        return row is not None
