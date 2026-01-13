import asyncio
import logging
import csv
import time
from typing import Dict, Optional
from playwright.async_api import async_playwright, Browser, Playwright
from browser_session import Session

logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self, max_sessions: int = 5, idle_timeout: int = 300):
        self.max_sessions = max_sessions
        self.idle_timeout = idle_timeout
        self.sessions: Dict[str, Session] = {}
        self.session_locks: Dict[str, asyncio.Lock] = {}
        self.active_sessions: set[str] = set() # Sessions currently "checked out"
        self._pool_lock = asyncio.Lock() # Lock for modifying the session pool
        self.last_used: Dict[str, float] = {}
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.credentials: Dict[str, str] = {}
        self._load_credentials()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    def _load_credentials(self):
        try:
            with open('credentials.csv', newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    self.credentials[row['username']] = row['password']
        except Exception as e:
            logger.error(f"Failed to load credentials: {e}")

    async def start(self, headless=True):
        if self._running:
            return
        self._running = True
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=headless)
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("SessionManager started.")

    async def stop(self):
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        for username, session in self.sessions.items():
            await session.close()
        self.sessions.clear()
        
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("SessionManager stopped.")

    async def get_session(self, username: str) -> Session:
        if username not in self.credentials:
            raise ValueError(f"No credentials found for user {username}")

        # Ensure lock exists safely
        async with self._pool_lock:
            if username not in self.session_locks:
                self.session_locks[username] = asyncio.Lock()
            user_lock = self.session_locks[username]

        async with user_lock:
            # Check if session exists
            async with self._pool_lock:
                if username in self.sessions:
                    self.last_used[username] = time.time()
                    self.active_sessions.add(username)
                    return self.sessions[username]

                # Check if we need to make room
                if len(self.sessions) >= self.max_sessions:
                    await self._prune_sessions()
                    if len(self.sessions) >= self.max_sessions:
                         raise Exception("Max sessions reached and no idle sessions available to prune.")

                # Reserve the slot and create session object
                session = Session(self.browser)
                self.sessions[username] = session
                self.active_sessions.add(username)
                self.last_used[username] = time.time()

            # Perform login outside the pool lock but inside user lock
            try:
                await session.start()
                await session.login(username, self.credentials[username], "loyalty")
            except Exception as e:
                # Cleanup if failed
                async with self._pool_lock:
                    if username in self.sessions:
                        del self.sessions[username]
                    if username in self.active_sessions:
                        self.active_sessions.remove(username)
                await session.close()
                raise e
            
            return session

    async def release_session(self, username: str):
        async with self._pool_lock:
            if username in self.active_sessions:
                self.active_sessions.remove(username)
            if username in self.last_used:
                self.last_used[username] = time.time()

    async def _prune_sessions(self):
        # Close oldest session that is NOT active
        if not self.sessions:
            return
        
        # Sort by last used
        sorted_sessions = sorted(self.last_used.items(), key=lambda item: item[1])
        
        username_to_remove = None
        for username, _ in sorted_sessions:
            if username not in self.active_sessions:
                username_to_remove = username
                break
        
        if username_to_remove:
            logger.info(f"Pruning session for {username_to_remove}")
            await self._close_session(username_to_remove)
        else:
            logger.warning("Could not prune any sessions, all are active.")

    async def _close_session(self, username: str):
        if username in self.sessions:
            session = self.sessions[username]
            await session.close()
            del self.sessions[username]
        if username in self.last_used:
            del self.last_used[username]
        if username in self.session_locks:
            del self.session_locks[username]

    async def _cleanup_loop(self):
        while self._running:
            await asyncio.sleep(60)
            now = time.time()
            to_remove = []
            async with self._pool_lock:
                for username, last_time in self.last_used.items():
                    if now - last_time > self.idle_timeout and username not in self.active_sessions:
                        to_remove.append(username)
                
                for username in to_remove:
                    logger.info(f"Session for {username} timed out.")
                    await self._close_session(username)
