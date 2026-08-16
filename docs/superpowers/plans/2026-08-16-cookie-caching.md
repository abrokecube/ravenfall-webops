# Cookie Caching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist each account's authenticated browser state (cookies + localStorage) to disk so sessions can be reopened without a full login.

**Architecture:** Each `Session` gets its own `BrowserContext`, seeded from a cached Playwright `storage_state` on disk. On session creation, navigate to `/loyalty` and check for `.rf-stats`; if present the cached login is valid, otherwise run the existing full login. `SessionManager` orchestrates load/save of the cache files.

**Tech Stack:** Python 3.12, Playwright (async), uv, pytest (dev), FastAPI (unchanged).

**Spec:** `docs/superpowers/specs/2026-08-16-cookie-caching-design.md`

---

## File Structure

- Create: `storage.py` — pure load/save/delete of `.storage/<username>.json` (atomic writes).
- Create: `conftest.py` — empty file at project root so pytest adds the project root to `sys.path` (needed for `import storage`).
- Create: `tests/test_storage.py` — unit tests for `storage.py`.
- Create: `scripts/verify_cookie_caching.py` — live-site integration verification.
- Modify: `browser_session.py` — `Session` per-user context, cache-aware `login()`, `_is_logged_in()`, `get_storage_state()`.
- Modify: `session_manager.py` — load cache on session creation, save after login and on close/stop.
- Modify: `.gitignore` — ignore `.storage/`.
- Modify: `README.md` — document cookie caching.

---

### Task 1: pytest dev dependency + storage module

**Files:**
- Modify: `pyproject.toml` (via `uv add`)
- Create: `storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Add pytest as a dev dependency**

Run: `uv add --dev pytest`
Expected: `pyproject.toml` and `uv.lock` updated.

- [ ] **Step 2: Write the failing tests**

Create an empty `conftest.py` at the project root (no content).

Create `tests/test_storage.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_storage.py -v`
Expected: `FAIL` with `ModuleNotFoundError: No module named 'storage'`

- [ ] **Step 4: Write the minimal implementation**

Create `storage.py`:

```python
import json
import logging
import os

logger = logging.getLogger(__name__)

STORAGE_DIR = os.getenv("STORAGE_DIR", ".storage")


def storage_path(username: str) -> str:
    return os.path.join(STORAGE_DIR, f"{username}.json")


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
    os.makedirs(STORAGE_DIR, exist_ok=True)
    path = storage_path(username)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def delete_storage(username: str) -> None:
    try:
        os.remove(storage_path(username))
    except OSError:
        pass
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_storage.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add conftest.py storage.py tests/test_storage.py pyproject.toml uv.lock
git commit -m "feat: add cookie storage module with unit tests"
```

---

### Task 2: Write the integration verification script (failing test for the feature)

**Files:**
- Create: `scripts/verify_cookie_caching.py`

- [ ] **Step 1: Write the integration verification script**

Create `scripts/verify_cookie_caching.py`:

```python
import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_session
import storage
from session_manager import SessionManager

USERNAME = "hackedcube"
login_results = []


async def main():
    tmpdir = tempfile.mkdtemp()
    storage.STORAGE_DIR = tmpdir

    original_login = browser_session.Session.login

    async def spy_login(self, username, password, redirect=None):
        result = await original_login(self, username, password, redirect)
        login_results.append(result)
        return result

    browser_session.Session.login = spy_login

    # 1. Fresh login (no cache) must create the cache file
    sm = SessionManager()
    await sm.start(headless=True)
    session = await sm.get_session(USERNAME)
    points = await session.get_loyalty_points()
    await sm.release_session(USERNAME)
    print("fresh points:", points)
    assert login_results == [False], f"expected fresh login, got {login_results}"
    cache_path = storage.storage_path(USERNAME)
    assert os.path.exists(cache_path), "cache file was not created"
    print("fresh login created cache")

    # 2. Restart the manager (simulates server restart): cache must be reused
    login_results.clear()
    await sm.stop()

    sm2 = SessionManager()
    await sm2.start(headless=True)
    session = await sm2.get_session(USERNAME)
    points2 = await session.get_loyalty_points()
    await sm2.release_session(USERNAME)
    print("cached points:", points2)
    assert login_results == [True], f"expected cached login, got {login_results}"
    assert points2 > 0
    print("cached login reused after restart")
    await sm2.stop()

    # 3. Corrupt cache forces a fresh login and a rewritten cache file
    login_results.clear()
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write("garbage not json")

    sm3 = SessionManager()
    await sm3.start(headless=True)
    session = await sm3.get_session(USERNAME)
    points3 = await session.get_loyalty_points()
    await sm3.release_session(USERNAME)
    print("after-corruption points:", points3)
    assert login_results == [False], f"expected fresh login after corruption, got {login_results}"
    assert points3 > 0
    with open(cache_path, encoding="utf-8") as f:
        json.load(f)
    print("corrupt cache triggered fresh login and rewrite")
    await sm3.stop()

    print("ALL CHECKS PASSED")


asyncio.run(main())
```

- [ ] **Step 2: Run the script to verify it fails**

Run: `uv run python scripts/verify_cookie_caching.py`
Expected: `FAIL` with `TypeError: Session.__init__() got an unexpected keyword argument 'storage_state'` (or an `AssertionError` because the cache file is not created).

- [ ] **Step 3: Commit**

```bash
git add scripts/verify_cookie_caching.py
git commit -m "test: add cookie caching integration verification script"
```

---

### Task 3: Session per-user context + cache-aware login

**Files:**
- Modify: `browser_session.py`

- [ ] **Step 1: Update `Session.__init__`, `start`, and `close`**

Replace the current `Session.__init__`, `start`, and `close` methods with:

```python
    def __init__(self, browser: 'Browser', storage_state=None):
        self.browser = browser
        self.context = None
        self.page: Page | None = None
        self.login_username: str | None = None
        self.storage_state = storage_state
        
    async def start(self):
        if self.storage_state:
            self.context = await self.browser.new_context(storage_state=self.storage_state)
        else:
            self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        logger.info("Session started, new page created.")
        
    async def close(self):
        if self.context:
            await self.context.close()
            self.context = None
            self.page = None
            self.login_username = None
            logger.info("Session closed, page closed.")
```

- [ ] **Step 2: Update `login` to verify cached state first, and add `_is_logged_in` + `storage_state`**

Replace the current `login` method and add two new methods after it:

```python
    async def login(self, username: str, password: str, redirect: str = None):
        if self.page is None:
            raise Exception("Session not started. Call start() before login().")

        # Reuse a cached login if present and still valid
        if self.storage_state:
            await self.goto_if_not("https://www.ravenfall.stream/loyalty")
            if await self._is_logged_in():
                self.login_username = username
                logger.info(f"Using cached login for {username}.")
                return True

        logger.info(f"Logging in as {username}.")
        url = "https://www.ravenfall.stream/login"
        if redirect:
            url += "/redirect/" + redirect
        await self.goto_if_not(url)
        await self.page.get_by_role("textbox", name="USERNAME").fill(username)
        await self.page.get_by_role("textbox", name="PASSWORD").fill(password)
        await asyncio.sleep(0.5)
        await self.page.get_by_role("button", name="Sign in").click()
        
        if redirect:
            await self.page.wait_for_url(f"https://www.ravenfall.stream/{redirect}", timeout=60000)
        else:
            await self.page.wait_for_url("https://www.ravenfall.stream/", timeout=60000)
        self.login_username = username
        logger.info(f"Logged in as {username}.")
        return False

    async def _is_logged_in(self) -> bool:
        try:
            await self.page.locator(".rf-stats").wait_for(state="visible", timeout=5000)
            return True
        except TimeoutError:
            return False

    async def get_storage_state(self):
        if self.context:
            return await self.context.storage_state()
        return None
```

- [ ] **Step 3: Update `logout` to drop the in-memory cache**

Replace the current `logout` method body (after `self.login_username = None`) so it also resets the cache reference:

```python
    async def logout(self):
        if self.page is None:
            raise Exception("Session not started. Call start() before logout().")
        
        await self.page.goto("https://www.ravenfall.stream/logout")
        await self.page.wait_for_url("https://www.ravenfall.stream/")
        self.login_username = None
        self.storage_state = None
```

- [ ] **Step 4: Sanity check the module imports and compiles**

Run: `uv run python -m py_compile browser_session.py`
Expected: no output (exit code 0).

- [ ] **Step 5: Commit**

```bash
git add browser_session.py
git commit -m "feat: per-user browser context with cached-login verification"
```

---

### Task 4: SessionManager persistence wiring

**Files:**
- Modify: `session_manager.py`

- [ ] **Step 1: Import the storage helpers**

Add to the imports at the top of `session_manager.py` (after `from browser_session import Session`):

```python
from storage import load_storage, save_storage
```

- [ ] **Step 2: Seed the session with the cached state and save after login**

In `get_session`, replace the session creation and login block:

```python
                    # Reserve the slot and create session object
                    session = Session(self.browser, storage_state=load_storage(username))
                    self.sessions[username] = session
                    self.active_sessions.add(username)
                    self.last_used[username] = time.time()

                # Perform login outside the pool lock but inside user lock
                try:
                    await session.start()
                    await session.login(username, self.credentials[username], "loyalty")
                    save_storage(username, await session.get_storage_state())
                except Exception as e:
```

- [ ] **Step 3: Add a `_persist_session` helper**

Add this method to `SessionManager` (e.g. before `_close_session`):

```python
    async def _persist_session(self, username: str):
        session = self.sessions.get(username)
        if session is None or not session.login_username:
            return
        try:
            save_storage(username, await session.get_storage_state())
        except Exception:
            logger.exception(f"Failed to persist storage for {username}")
```

- [ ] **Step 4: Persist before closing sessions**

Replace `_close_session`:

```python
    async def _close_session(self, username: str):
        if username in self.sessions:
            session = self.sessions[username]
            await self._persist_session(username)
            await session.close()
            del self.sessions[username]
        if username in self.last_used:
            del self.last_used[username]
        if username in self.session_locks:
            del self.session_locks[username]
```

Replace the session-close loop in `stop`:

```python
        for username, session in self.sessions.items():
            await self._persist_session(username)
            await session.close()
        self.sessions.clear()
```

- [ ] **Step 5: Sanity check the module compiles**

Run: `uv run python -m py_compile session_manager.py`
Expected: no output (exit code 0).

- [ ] **Step 6: Commit**

```bash
git add session_manager.py
git commit -m "feat: persist and restore account sessions via SessionManager"
```

---

### Task 5: Full integration verification

**Files:**
- Modify: none (runs the script from Task 2)

- [ ] **Step 1: Run the integration verification script**

Run: `uv run python scripts/verify_cookie_caching.py`
Expected output (no assertions failing):

```
fresh points: <N>
fresh login created cache
cached points: <N>
cached login reused after restart
after-corruption points: <N>
corrupt cache triggered fresh login and rewrite
ALL CHECKS PASSED
```

Note: this performs fresh logins for the `hackedcube` account (two full logins) but no purchases.

- [ ] **Step 2: Verify the API endpoints still work with caching**

Start the server in the background and hit the endpoints (this reuses the `hackedcube` cache written in Step 1):

Run: `HEADLESS=true uv run python main.py &`
Wait ~15s, then:

```bash
uv run python -c "import asyncio; from client import RavenfallClient; c = RavenfallClient(); print(asyncio.run(c.get_total_loyalty_points(['hackedcube'])))"
```

Expected: `{'status': 'success', 'total_points': <N>, 'breakdown': {'hackedcube': <N>}}`

Then kill the server process (e.g. `kill %1` in the same shell, or via the `pid` file written by `main.py`).

- [ ] **Step 3: Confirm the cache file exists and is gitignored**

Run: `ls .storage/`
Expected: `hackedcube.json` present.

Run: `git check-ignore .storage/hackedcube.json`
Expected: the path printed (file is ignored) — this requires the Task 6 `.gitignore` change; if not yet applied, verify `.storage/` is untracked and not staged.

---

### Task 6: .gitignore + README

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`

- [ ] **Step 1: Ignore the storage directory**

Add `.storage/` to `.gitignore`:

```
.storage/
```

- [ ] **Step 2: Document cookie caching in the README**

Add a section to `README.md`:

```markdown
### Cookie caching
Authenticated sessions are cached in `.storage/` (one JSON file per account) so accounts
are not logged in from scratch on every session. Set `STORAGE_DIR` to change the location.
Delete a file to force that account to log in again on next use.
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore README.md
git commit -m "chore: ignore cached sessions and document cookie caching"
```

---

## Self-Review

**Spec coverage:**
- storage.py load/save/delete → Task 1 ✓
- Session per-user context + cached verify + storage_state accessor → Task 3 ✓
- SessionManager load-on-create / save-after-login / save-on-close-and-stop → Task 4 ✓
- Expired/corrupt cache handled (verify fails → full login → rewrite) → Task 5 step 1 (case 3) ✓
- Server-restart reuse → Task 5 step 1 (case 2) ✓
- API endpoint regression → Task 5 step 2 ✓
- `.storage/` gitignored → Task 6 ✓
- Logout resets in-memory cache → Task 3 step 3 ✓