import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

STORAGE_DIR = os.getenv("STORAGE_DIR", ".storage")


def storage_path(username: str) -> Path:
    return Path(STORAGE_DIR) / f"{username}.json"


def load_storage(username: str):
    path = storage_path(username)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        logger.debug(f"No valid cached storage for {username} at {path}")
        return None


def save_storage(username: str, state) -> None:
    if state is None:
        return
    path = storage_path(username)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def delete_storage(username: str) -> None:
    try:
        storage_path(username).unlink()
    except OSError:
        pass