import pytest

import storage as storage_mod


@pytest.fixture()
def tmp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_mod, "STORAGE_DIR", str(tmp_path))
    return tmp_path


def test_load_missing_returns_none(tmp_storage):
    assert storage_mod.load_storage("nobody") is None


def test_save_and_load_roundtrip(tmp_storage):
    state = {"cookies": [{"name": "x", "value": "1"}], "origins": []}
    storage_mod.save_storage("alice", state)
    assert storage_mod.load_storage("alice") == state


def test_load_corrupt_returns_none(tmp_storage):
    path = storage_mod.storage_path("bob")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert storage_mod.load_storage("bob") is None


def test_save_none_is_noop(tmp_storage):
    storage_mod.save_storage("carol", None)
    assert not storage_mod.storage_path("carol").exists()


def test_delete_removes_file(tmp_storage):
    storage_mod.save_storage("dave", {"cookies": []})
    storage_mod.delete_storage("dave")
    assert not storage_mod.storage_path("dave").exists()


def test_delete_missing_is_noop(tmp_storage):
    storage_mod.delete_storage("missing")
    assert not storage_mod.storage_path("missing").exists()


def test_load_invalid_username_returns_none(tmp_storage):
    assert storage_mod.load_storage("../evil") is None


def test_load_schema_invalid_returns_none(tmp_storage):
    storage_mod.save_storage("eve", {"cookies": []})
    assert storage_mod.load_storage("eve") is None


def test_load_schema_valid_returns_state(tmp_storage):
    state = {"cookies": [{"name": "x", "value": "1", "domain": "example.com", "path": "/"}], "origins": []}
    storage_mod.save_storage("frank", state)
    assert storage_mod.load_storage("frank") == state
