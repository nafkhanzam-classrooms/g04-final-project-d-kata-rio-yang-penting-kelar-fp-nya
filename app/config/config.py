import os
from pathlib import Path

try:
    from dotenv import load_dotenv as _load_dotenv
except ImportError:
    def _load_dotenv(**_: object) -> bool:
        return False


DEFAULTS = {
    "JWT_SECRET": "codedu_secret_key_change_in_production",
    "DB_PATH": "codedu.db",
    "HOST": "0.0.0.0",
    "PORT": "8000",
}


def get_project_root() -> Path:
    """Return the absolute path to the project root."""
    return Path(__file__).resolve().parent.parent.parent


def load_env_file(path: str | Path | None = None) -> None:
    """Load a .env file from a directory, file path, or project root."""
    if path is None:
        env_path = get_project_root() / ".env"
    else:
        resolved_path = Path(path).resolve()
        if resolved_path.is_dir():
            env_path = resolved_path / ".env"
        elif resolved_path.name == ".env":
            env_path = resolved_path
        else:
            env_path = resolved_path.parent / ".env"

    if env_path.is_file():
        _load_dotenv(dotenv_path=env_path)
        print(f"[CONFIG] Loaded .env from {env_path}")
    else:
        print(f"[CONFIG] No .env file found at {env_path}, using defaults")


def test_env() -> None:
    print(os.environ.get("TEST"))


def get_config(key: str, default: str | None = None) -> str | None:
    """Return a configuration value from the environment or defaults."""
    return os.environ.get(key, DEFAULTS.get(key, default))


def get_jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", DEFAULTS["JWT_SECRET"])


def get_db_path() -> str:
    return os.environ.get("DB_PATH", DEFAULTS["DB_PATH"])


def get_public_dir() -> Path:
    """Return the absolute path to the public directory."""
    return get_project_root() / "public"


def get_upload_dir() -> Path:
    """Return the uploads directory, creating it when necessary."""
    upload_dir = get_project_root() / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir
