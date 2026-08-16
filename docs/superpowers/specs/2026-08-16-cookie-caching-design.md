# Cookie Caching for Ravenfall Sessions

Date: 2026-08-16

## Goal

Avoid logging into Ravenfall every time a session is created for an account. Reuse an
already-authenticated session via persisted browser cookies/storage so that re-opening a
session after it was pruned or after a server restart does not require the full login flow.

## Background

`SessionManager` launches a single Chromium browser and pools one `Session` per username.
Sessions are pruned after `idle_timeout` (300s) or when capacity is needed, and the pool is
reset on server restart. Every newly created `Session` currently performs a full login
(visit `/login/redirect/loyalty`, fill USERNAME/PASSWORD, click "Sign in").

All sessions currently share the browser's default context (`browser.new_page()`). This
makes per-user cookie handling impossible without change, because cookies would leak
between accounts sharing that context.

## Approach

Per-user `BrowserContext` seeded with a cached Playwright `storage_state` (cookies +
localStorage), persisted to disk, with verify-on-use.

### Components

**New module `storage.py`**

- `load_storage(username) -> dict | None` — reads `.storage/<username>.json`. Returns
  `None` on missing file, corrupt JSON, or read errors.
- `save_storage(username, state)` — writes atomically (temp file + `os.replace`), creating
  `.storage/` if needed. No-op if `state` is `None`.
- `delete_storage(username)` — removes the file if present.
- Storage dir resolved from `STORAGE_DIR` env var, defaulting to `.storage`.
- `.storage/` is gitignored (contains authenticated session tokens).

**`Session` (`browser_session.py`)**

- `__init__(self, browser, storage_state=None)` — stores the cached state.
- `start()` — creates `self.context` via `browser.new_context(storage_state=...)` when a
  cache exists, otherwise `browser.new_context()`, then `self.page = context.new_page()`.
- `close()` — closes the context; resets `context`, `page`, `login_username`.
- `login(username, password, redirect=None)` — first, if a cache exists, navigates to
  `https://www.ravenfall.stream/loyalty` and waits up to ~3s for `.rf-stats` to become
  visible. Visible => already authenticated (returns `True`, no credentials typed).
  Otherwise performs the existing full login flow (returns `False`).
- `get_storage_state()` — returns `await self.context.storage_state()` when a context exists,
  else `None`.
- `logout()` — unchanged in behavior; also resets the in-memory cache reference.

**`SessionManager` (`session_manager.py`)**

- `get_session()` — loads `load_storage(username)` and passes it to `Session`. After a
  successful `start()` + `login()`, saves `save_storage(username, await session.get_storage_state())`.
- `_close_session()` and `stop()` — before closing a session whose `login_username` is set,
  save its current `get_storage_state()` (captures any cookie rotation during the session).
- Cleanup on login failure unchanged: session closed, cache not written for that attempt.

### Data Flow

1. `get_session(user)` → `cached = load_storage(user)` → `Session(browser, storage_state=cached)`
   → `start()` (context seeded with cached cookies/localStorage) → `login(user, pass, "loyalty")`.
2. `login()`: cache present => navigate to `/loyalty`, wait for `.rf-stats`. Found => logged
   in; `login_username` set; return `True`. Not found => run the full login flow; return `False`.
3. After a successful login (either path), `SessionManager` persists the context's
   `get_storage_state()` to `.storage/<user>.json`.
4. On prune or shutdown, sessions that were logged in have their `get_storage_state()` saved
   before the context is closed.

### Logged-In Check

The loyalty page renders `.rf-stats` only when authenticated. When logged out, `/loyalty`
redirects to `/login/redirect/loyalty` (login form), which has no `.rf-stats`. `wait_for`
with a short timeout distinguishes the two states reliably despite Blazor's server-side
render latency.

### Error Handling

- Expired/invalid cache: verify fails, full login runs, cache overwritten.
- Corrupt or missing cache file: treated as no cache.
- Playwright rejects a malformed `storage_state`: `load_storage` returns `None`, so
  `new_context` is called without it.
- Login failure: session cleaned up as today; no cache write for that attempt.

### Testing

Verify with the `hackedcube` account:

1. Fresh login (no cache): a `.storage/hackedcube.json` file is created; `login()` returns `False`.
2. Cached reuse: close the session (or prune it), open again; `login()` returns `True` and
   the login form is never touched; `get_loyalty_points` still works.
3. Stale cache: corrupt the file (e.g., remove the auth cookie), reopen; a full login runs
   and the file is rewritten.
4. Server restart simulation: stop and re-`start()` the `SessionManager`; the cached session
   is reused without a fresh login.
5. Regression: `/loyalty/points` and `/redeem` API endpoints still work.

## Out of Scope

- Changing the `idle_timeout` pruning behavior.
- Multi-browser-process approaches (e.g. `launch_persistent_context` per user).
- Clearing the cache from `logout()` (not used by the automations).