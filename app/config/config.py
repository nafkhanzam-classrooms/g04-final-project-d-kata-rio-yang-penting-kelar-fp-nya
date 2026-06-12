import os
from pathlib import Path
from dotenv import load_dotenv

def load_env_file(path: str) -> None :
    env_path = Path(path).resolve() / ".env"
    load_dotenv(dotenv_path=env_path)

def test_env() -> None:
    print(os.environ.get('TEST'))
