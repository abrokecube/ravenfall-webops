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


def load_storage(username: str):
    try:
        path = storage_path(username)
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict) or not isinstance(state.get("cookies"), list) or not isinstance(state.get("origins"), list):
            logger.debug(f"No valid cached storage for {username}")
            return None
        return state
    except (OSError, json.JSONDecodeError, ValueError):
        logger.debug(f"No valid cached storage for {username}")
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
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def delete_storage(username: str) -> None:
    try:
        storage_path(username).unlink()
    except (OSError, ValueError):
        pass
