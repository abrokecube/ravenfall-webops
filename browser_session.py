import asyncio
from playwright.async_api import async_playwright, expect
from typing import TYPE_CHECKING
import csv
import logging

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page

logger = logging.getLogger(__name__)


class InsufficientPointsError(Exception):
    pass

class RedemptionFailedError(Exception):
    pass

class Session:
    def __init__(self, browser: 'Browser'):
        self.browser = browser
        self.page: Page | None = None
        self.login_username: str | None = None
        
    async def start(self):
        self.page = await self.browser.new_page()
        logger.info("Session started, new page created.")
        
    async def close(self):
        if self.page:
            await self.page.close()
            self.page = None
            logger.info("Session closed, page closed.")
            self.login_username = None
    
    async def login(self, username: str, password: str, redirect: str = None):
        if self.page is None:
            raise Exception("Session not started. Call start() before login().")
        
        logger.info(f"Logging in as {username}.")
        url = "https://www.ravenfall.stream/login"
        if redirect:
            url += "/redirect/" + redirect
        await self.goto_if_not(url)
        await self.page.get_by_role("textbox", name="USERNAME").fill(username)
        await self.page.get_by_role("textbox", name="PASSWORD").fill(password)
        await self.page.get_by_role("button", name="Login").click()
        
        if redirect:
            await self.page.wait_for_url(f"https://www.ravenfall.stream/{redirect}")
        else:
            await self.page.wait_for_url("https://www.ravenfall.stream/")
        self.login_username = username
        logger.info(f"Logged in as {username}.")
    
    async def logout(self):
        if self.page is None:
            raise Exception("Session not started. Call start() before logout().")
        
        await self.page.goto("https://www.ravenfall.stream/logout")
        await self.page.wait_for_url("https://www.ravenfall.stream/")
        self.login_username = None
        
    async def goto_if_not(self, url: str):
        if self.page is None:
            raise Exception("Session not started. Call start() before goto_if_not().")
        
        if self.page.url != url:
            await self.page.goto(url, wait_until="networkidle")
            
    async def get_loyalty_points(self) -> int:
        if self.page is None:
            raise Exception("Session not started. Call start() before get_loyalty_points().")
        
        await self.goto_if_not("https://www.ravenfall.stream/loyalty")
        points = await self.page.locator("body > div.page.dashboard > div.main > div.content.px-4 > div.loyalty-streamer-details > div.loyalty-stats-rows > div.stats-row.points > div.stats-value").inner_text()
        return int(points)
    
    async def redeem_loyalty_item(self, item_name: str, quantity: int = 1, character_idx: int = 1):
        if self.page is None:
            raise Exception("Session not started. Call start() before redeem_loyalty_item().")
        
        character_idx = max(character_idx, 1)
    
        await self.goto_if_not("https://www.ravenfall.stream/loyalty")
        
        redeem_button_locator = self.page.get_by_text(item_name).locator("../..").locator(".btn-reward-redeem")
        combobox = self.page.get_by_role("combobox")        
        option_locator = self.page.get_by_role("option")
        
        await asyncio.sleep(0.5)
        for _ in range(10):        
            await redeem_button_locator.click()
            if await combobox.is_visible():
                break
            await asyncio.sleep(1)
        else:
            raise Exception("Redeem dialog did not appear.")
        texts = await option_locator.all_text_contents()
        matched = False
        for i, t in enumerate(texts):
            if t.strip().endswith(f"#{character_idx-1}"):
                await combobox.select_option(value=t)
                matched = True
                break
            
        if not matched:
            raise RedemptionFailedError(f"No matching character option found for index {character_idx} (characters: {texts})")

        await self.page.get_by_role("spinbutton").fill(str(quantity))
        close_button = self.page.get_by_role("button", name="×")
        try:            
            await self.page.get_by_role("button", name="Redeem", exact=True).click(timeout=2000)
            await close_button.wait_for(state="detached", timeout=5000)
            
        except Exception as e:
            # If the dialog is still open, it likely failed.
            if await close_button.is_visible():
                await close_button.click()
                # Try to read error message if any?
                # For now, raise a generic RedemptionFailedError or InsufficientPointsError if we suspect it.
                # Since we can't easily distinguish without more UI knowledge, we'll wrap it.
                raise RedemptionFailedError(f"Redemption failed: {str(e)}")
            raise e


credentials = {}
with open('credentials.csv', newline='') as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        credentials[row['username']] = row['password']

async def main():
    async with async_playwright() as p:
        # browser = await p.chromium.launch(headless=False)
        browser = await p.chromium.launch()
        session = Session(browser)
        await session.start()
        login = "queuedcube"
        await session.login(login, credentials[login], "loyalty")
        print(f"Loyalty Points: {await session.get_loyalty_points()}")
        await session.redeem_loyalty_item("Raid Scroll", 1, 1)
        print(f"Loyalty Points after: {await session.get_loyalty_points()}")
        await browser.close()        

if __name__ == "__main__":
    asyncio.run(main())
