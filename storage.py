import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

STORAGE_DIR = os.getenv("STORAGE_DIR", ".storage")


def storage_path(username: str) -> Path:
    if not username or username in (".", "..") or "/" in username or "\\" in username:
        raise ValueError(f"Invalid storage username: {username!r}")
    return Path(STORAGE_DIR) / f"{username}.json"


def load_storage(username: str) -> dict | None:
    path = storage_path(username)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        logger.debug(f"No valid cached storage for {username} at {path}")
        return None


def save_storage(username: str, state: dict | None) -> None:
    if state is None:
        return
    path = storage_path(username)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)


def delete_storage(username: str) -> None:
    try:
        storage_path(username).unlink()
    except OSError:
        pass
