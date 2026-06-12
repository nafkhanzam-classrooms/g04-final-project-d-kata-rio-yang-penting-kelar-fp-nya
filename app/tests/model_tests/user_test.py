# tests for Database (connection.py) and UserRepository (user.py).

# Run with:
# pip install pytest mysql-connector-python
# python -m pytest path/to/test_db.py -v
#
# No real MySQL server needed — all DB calls are mocked.

import os
import pytest
from unittest.mock import MagicMock, patch, call


# helper functionss: build lightweight fakes

def make_mock_cursor(rows=None, one_row=None, lastrowid=None, rowcount=1):
    # return a mock cursor pre-loaded with canned results
    cur = MagicMock()
    cur.fetchall.return_value = rows or []
    cur.fetchone.return_value = one_row
    cur.lastrowid = lastrowid
    cur.rowcount = rowcount
    return cur


def make_mock_conn(cursor):
    # return a mock PooledMySQLConnection that yields cursor.
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn

# tests

class TestDatabase:
    """Unit tests for the Database wrapper."""


    @pytest.fixture
    def db(self):
        # database instance with a mocked connection pool.
        with patch("mysql.connector.pooling.MySQLConnectionPool") as MockPool:
            from app.config.db.connection import Database # adjusted module path
            instance = Database(
                host="localhost", port=3306,
                user="root",     password=str(os.environ.get("DB_PASSWORD")),
                database="test",
            )
            instance._pool = MockPool.return_value   # swap pool with mock
            return instance

    # tests for fetch all
    def test_fetch_all_returns_list_of_dicts(self, db):
        rows = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        cur  = make_mock_cursor(rows=rows)
        conn = make_mock_conn(cur)
        db._pool.get_connection.return_value = conn

        result = db.fetch_all("SELECT * FROM users")

        assert result == rows
        cur.execute.assert_called_once_with("SELECT * FROM users", ())

    def test_fetch_all_passes_params(self, db):
        cur  = make_mock_cursor(rows=[])
        conn = make_mock_conn(cur)
        db._pool.get_connection.return_value = conn

        db.fetch_all("SELECT * FROM users WHERE role = %s", ("admin",))

        cur.execute.assert_called_once_with(
            "SELECT * FROM users WHERE role = %s", ("admin",)
        )

    def test_fetch_all_empty_result(self, db):
        cur  = make_mock_cursor(rows=[])
        conn = make_mock_conn(cur)
        db._pool.get_connection.return_value = conn

        result = db.fetch_all("SELECT * FROM users WHERE 1=0")

        assert result == []

    # tests for fetch one
    def test_fetch_one_returns_dict(self, db):
        row  = {"id": 1, "username": "alice"}
        cur  = make_mock_cursor(one_row=row)
        conn = make_mock_conn(cur)
        db._pool.get_connection.return_value = conn

        result = db.fetch_one("SELECT * FROM users WHERE id = %s", (1,))

        assert result == row

    def test_fetch_one_returns_none_when_missing(self, db):
        cur  = make_mock_cursor(one_row=None)
        conn = make_mock_conn(cur)
        db._pool.get_connection.return_value = conn

        result = db.fetch_one("SELECT * FROM users WHERE id = %s", (999,))

        assert result is None

    # tests for execute
    def test_execute_insert_returns_lastrowid(self, db):
        cur  = make_mock_cursor(lastrowid=42)
        conn = make_mock_conn(cur)
        db._pool.get_connection.return_value = conn

        new_id = db.execute(
            "INSERT INTO users (username) VALUES (%s)", ("alice",)
        )

        assert new_id == 42

    def test_execute_update_returns_rowcount(self, db):
        cur  = make_mock_cursor(lastrowid=None, rowcount=3)
        conn = make_mock_conn(cur)
        db._pool.get_connection.return_value = conn

        affected = db.execute(
            "UPDATE users SET is_active = %s WHERE role_id = %s", (False, 2)
        )

        assert affected == 3

    # tests for execute many
    def test_execute_many_returns_rowcount(self, db):
        cur  = make_mock_cursor(rowcount=2)
        conn = make_mock_conn(cur)
        db._pool.get_connection.return_value = conn

        count = db.execute_many(
            "INSERT INTO users (username) VALUES (%s)",
            [("alice",), ("bob",)],
        )

        assert count == 2
        cur.executemany.assert_called_once()

    # test for ping the DB
    def test_ping_returns_true_on_success(self, db):
        cur  = make_mock_cursor(one_row={"1": 1})
        conn = make_mock_conn(cur)
        db._pool.get_connection.return_value = conn

        assert db.ping() is True

    def test_ping_returns_false_on_error(self, db):
        db._pool.get_connection.side_effect = Exception("connection refused")

        assert db.ping() is False

    # test for transaction, commit, rollback
    def test_transaction_commits_on_success(self, db):
        cur  = make_mock_cursor()
        conn = make_mock_conn(cur)
        db._pool.get_connection.return_value = conn

        with db.transaction() as c:
            c.execute("UPDATE users SET is_active = 1 WHERE id = 1")

        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_transaction_rolls_back_on_exception(self, db):
        cur  = make_mock_cursor()
        conn = make_mock_conn(cur)
        db._pool.get_connection.return_value = conn

        with pytest.raises(RuntimeError):
            with db.transaction():
                raise RuntimeError("something went wrong")

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    # test from loading from ENV (mock)
    def test_from_env_reads_environment(self, monkeypatch):
        monkeypatch.setenv("DB_HOST",     "db.example.com")
        monkeypatch.setenv("DB_PORT",     "5506")
        monkeypatch.setenv("DB_USER",     "app_user")
        monkeypatch.setenv("DB_PASSWORD", "hunter2")
        monkeypatch.setenv("DB_NAME",     "myapp")

        with patch("mysql.connector.pooling.MySQLConnectionPool"):
            from app.config.db.connection import Database
            db = Database.from_env()

        assert db.host     == "db.example.com"
        assert db.port     == 5506
        assert db.user     == "app_user"
        assert db.password == "hunter2"
        assert db.database == "myapp"

# UserRepository model tests
class TestUserRepository:

    @pytest.fixture
    def repo(self):
        # UserRepository with a fully mocked Database.
        mock_db = MagicMock()

        # Import here so the class-level `from app.config.db.connection import Database`
        # doesn't need to resolve
        with patch.dict("sys.modules", {"app.config.db.connection": MagicMock()}):
            from app.models.user import UserRepository
            return UserRepository(mock_db), mock_db

    # tests for get_by_id
    def test_get_by_id_found(self, repo):
        repository, db = repo
        db.fetch_one.return_value = {"id": 1, "username": "alice"}

        result = repository.get_by_id(1)

        assert result["username"] == "alice"
        db.fetch_one.assert_called_once()

    def test_get_by_id_not_found(self, repo):
        repository, db = repo
        db.fetch_one.return_value = None

        result = repository.get_by_id(999)

        assert result is None
    # tests for get data by username

    def test_get_by_username_found(self, repo):
        repository, db = repo
        db.fetch_one.return_value = {
            "id": 1, "username": "alice", "password_hash": "hashed"
        }

        result = repository.get_by_username("alice")

        assert result["id"] == 1
        db.fetch_one.assert_called_once()

    def test_get_by_username_not_found(self, repo):
        repository, db = repo
        db.fetch_one.return_value = None

        result = repository.get_by_username("ghost")

        assert result is None

    # test for creating entry
    def test_create_returns_new_user_id(self, repo):
        repository, db = repo
        db.fetch_one.return_value = {"id": 2}   # viewer role lookup
        db.execute.return_value   = 10           # new user id

        new_id = repository.create("bob", "Bob Smith", "bob@x.com", "hash123")

        assert new_id == 10
        db.execute.assert_called_once()

    def test_create_raises_when_viewer_role_missing(self, repo):
        repository, db = repo
        db.fetch_one.return_value = None   # viewer role not found

        with pytest.raises(ValueError, match="Viewer role not found"):
            repository.create("bob", "Bob Smith", "bob@x.com", "hash123")

    # test for set a user active or delete

    def test_set_active_calls_execute(self, repo):
        repository, db = repo

        repository.set_active(1, False)

        db.execute.assert_called_once()
        args = db.execute.call_args[0]
        assert "is_active" in args[0]
        assert (False, 1) == args[1]

    def test_delete_calls_execute(self, repo):
        repository, db = repo

        repository.delete(5)

        db.execute.assert_called_once()
        args = db.execute.call_args[0]
        assert "DELETE" in args[0]
        assert (5,) == args[1]

    # tests when for assigning a role
    def test_assign_role_success(self, repo):
        repository, db = repo
        db.fetch_one.return_value = {"id": 3}   # role lookup

        repository.assign_role(1, "presenter")

        assert db.execute.call_count == 1

    def test_assign_role_raises_when_role_missing(self, repo):
        repository, db = repo
        db.fetch_one.return_value = None

        with pytest.raises(ValueError, match="Role 'ghost' does not exist"):
            repository.assign_role(1, "ghost")

    # tests for getting permissions from a user
    def test_get_permissions_returns_code_list(self, repo):
        repository, db = repo
        db.fetch_all.return_value = [
            {"code": "ppt.view"},
            {"code": "ppt.control"},
        ]

        perms = repository.get_permissions_for_user(1)

        assert perms == ["ppt.view", "ppt.control"]

    def test_get_permissions_empty(self, repo):
        repository, db = repo
        db.fetch_all.return_value = []

        perms = repository.get_permissions_for_user(99)

        assert perms == []

    # tests for confirming a user has the permission or not
    def test_has_permission_true(self, repo):
        repository, db = repo
        db.fetch_one.return_value = {"1": 1}

        assert repository.has_permission(1, "ppt.view") is True

    def test_has_permission_false(self, repo):
        repository, db = repo
        db.fetch_one.return_value = None

        assert repository.has_permission(1, "user.manage") is False

    # the same as the permission but now tests for role
    def test_has_role_true(self, repo):
        repository, db = repo
        db.fetch_one.return_value = {"1": 1}

        assert repository.has_role(1, "admin") is True

    def test_has_role_false(self, repo):
        repository, db = repo
        db.fetch_one.return_value = None

        assert repository.has_role(1, "admin") is False

    # test when removing a role
    def test_remove_role_resets_to_viewer(self, repo):
        repository, db = repo

        repository.remove_role(1)

        db.execute.assert_called_once()
        sql = db.execute.call_args[0][0]
        assert "viewer" in sql
