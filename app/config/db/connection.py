import os
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple, cast

# Lightweight MySQL connection wrapper.

# usage example
#     from app.db.connection import Database
#
#     db = Database(
#         host="localhost",
#         port=3306,
#         user="root",
#         password="secret",
#         database="myapp",
#     )
#
#     # Fetch all rows
#     users = db.fetch_all("SELECT * FROM users WHERE role = %s", ("admin",))
#
#     # Fetch a single row
#     user = db.fetch_one("SELECT * FROM users WHERE id = %s", (user_id,))
#
#     # Execute an INSERT/UPDATE/DELETE
#     new_id = db.execute("INSERT INTO users (name, role) VALUES (%s, %s)", ("Alice", "viewer"))
#
#     # Transaction block
#     with db.transaction() as cursor:
#         cursor.execute("UPDATE users SET role = %s WHERE id = %s", ("presenter", 1))
#         cursor.execute("INSERT INTO audit_log (user_id, action) VALUES (%s, %s)", (1, "role_change"))

from mysql.connector import pooling
from mysql.connector import MySQLConnection
from mysql.connector.pooling import (
    MySQLConnectionPool,
    PooledMySQLConnection,
)
from mysql.connector.cursor import MySQLCursor
from mysql.connector.errors import PoolError


# class for database wrapping around mysql connection pool

# query methods are parameterised (using %s) to prevent any threat against SQL injection
# to add a layer of security atleast in the data layer
class Database:
    # set default connection on localhost:3306 and using root usn and empty pw
    def __init__(
        self,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        database: str = "",
        pool_name: str = "app_pool",
        pool_size: int = 5,
    ) -> None:
        self.host     = host
        self.port     = port
        self.user     = user
        self.password = password
        self.database = database

        # connection pool version is used to maintain a persistent connection to the DB server
        self._pool = MySQLConnectionPool(
            pool_name=pool_name,
            pool_size=pool_size,
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            autocommit=True,
        )

    
    # factory design pattern to make the db instance from environment variables
    # auto search on the ENV that has prefix of "DB_"

    @classmethod
    def from_env(cls, prefix: str = "DB_") -> "Database":
        return cls(
            host=os.environ.get(f"{prefix}HOST", "localhost"),
            port=int(os.environ.get(f"{prefix}PORT", "3306")),
            user=os.environ.get(f"{prefix}USER", "root"),
            password=os.environ.get(f"{prefix}PASSWORD", ""),
            database=os.environ.get(f"{prefix}NAME", ""),
        )

    # get a connection from the pool, caller must close() it (returns to pool)
    # IMPORTANT! : close() after using the cursor() method or get_connection()
    def get_connection(self) -> PooledMySQLConnection:
        return self._pool.get_connection()

    # context manager yielding a cursor with autocommit
    # connection is automatically returned to the pool afterwards
    @contextmanager
    def cursor(self, dictionary: bool = True) -> Iterator[Any]:
        conn = self.get_connection()
        cur: Any = conn.cursor(dictionary=dictionary, prepared=True)
        try:
            yield cur
        finally:
            cur.close()
            conn.close()  # returns connection to the pool

    # context manager for multi statement transaction
    # COMMIT on success and ROLLBACK if an exception is caught
    @contextmanager
    def transaction(self, dictionary: bool = True) -> Iterator[Any]:
        conn = self.get_connection()
        # conn.autocommit = False
        conn.start_transaction()
        cur: MySQLCursor = conn.cursor(dictionary=dictionary)
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            # conn.autocommit = True
            conn.close()

    # run a SELECT and return all rows as list of DICTS
    def fetch_all(self, query: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute(query, params)
            return cast(List[Dict[str, Any]], cur.fetchall())

    # run an SELECT but returns only the first row as a DICT or none
    def fetch_one(self, query: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        """Run a SELECT and return the first row as a dict, or None."""
        with self.cursor() as cur:
            cur.execute(query, params)
            return cast(Optional[Dict[str, Any]], cur.fetchone())

    # run INSERT/UPDATE/DELETE
    # returns lastrowid if INSERT, and affected row count if UPDATE or DELETE
    def execute(self, query: str, params: Sequence[Any] = ()) -> int:
        with self.cursor(dictionary=False) as cur:
            cur.execute(query, params)
            if cur.lastrowid is not None:
                return int(cur.lastrowid)

            return int(cur.rowcount)

    # running the same statement for multiple parameter sets (for bulk INSERT / UPDATE)
    def execute_many(self, query: str, params_list: List[Sequence[Any]]) -> int:
        with self.cursor(dictionary=False) as cur:
            cur.executemany(query, params_list)
            return cur.rowcount

    # returns true if the connection established
    def ping(self) -> bool:
        try:
            with self.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return True
        except Exception as exc:
            print(f"[Database] ping failed: {exc}")
            return False

    # load a SQL schema file from the given path in the function param
    def load_schema(self, schema_path: str) -> None:
        with open(schema_path, "r") as f:
            sql_content = f.read()

        conn = self.get_connection()
        cur: MySQLCursor = conn.cursor()
        try:
            for statement in sql_content.split(";"):
                statement = statement.strip()
    
                if not statement:
                    continue

                cur.execute(statement)

            conn.commit()
            cur.close()

            print("[DATABASE] Schema Loaded")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()
