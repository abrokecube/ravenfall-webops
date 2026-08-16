"""Live-site integration verification for the cookie-caching feature.

Contract: ``Session.login()`` returns ``True`` when a cached login is reused
and ``False`` when a fresh login was performed. This script passes when the
caching feature works.

This script runs real logins for the ``hackedcube`` account, so it needs
live-site access and an entry for the account in ``credentials.csv``. It uses
an isolated temp storage dir and does not touch ``.storage/``.
"""

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

    # 4. Schema-invalid cache (valid JSON, wrong shape) also forces a fresh login
    login_results.clear()
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"cookies": []}, f)

    sm4 = SessionManager()
    await sm4.start(headless=True)
    session = await sm4.get_session(USERNAME)
    points4 = await session.get_loyalty_points()
    await sm4.release_session(USERNAME)
    print("after-schema-corruption points:", points4)
    assert login_results == [False], f"expected fresh login after schema corruption, got {login_results}"
    assert points4 > 0
    print("schema-invalid cache triggered fresh login")
    await sm4.stop()

    print("ALL CHECKS PASSED")


asyncio.run(main())