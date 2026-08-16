import asyncio
import csv
import logging
import os
import re
from playwright.async_api import async_playwright, TimeoutError
from typing import TYPE_CHECKING

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
        await asyncio.sleep(0.5)
        await self.page.get_by_role("button", name="Sign in").click()
        
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
        points = await self.page.locator(".rf-stat", has=self.page.get_by_text("Loyalty points", exact=True)).locator(".rf-stat__value").inner_text()
        return int(points.replace(",", "").strip())
    
    async def redeem_loyalty_item(self, item_name: str, quantity: int = 1, character_idx: int = 1):
        if self.page is None:
            raise Exception("Session not started. Call start() before redeem_loyalty_item().")
        
        character_idx = max(character_idx, 1)
    
        await self.goto_if_not("https://www.ravenfall.stream/loyalty")
        
        # Locate the reward card for the requested item, then its redeem button
        reward_card = self.page.locator(".rf-reward").filter(
            has=self.page.get_by_text(item_name, exact=True)
        )
        redeem_button_locator = reward_card.locator(".rf-reward__buy button")
        dialog = self.page.get_by_role("dialog")
        
        # Close any dialog left open by a previous attempt
        if await dialog.is_visible():
            await dialog.get_by_role("button", name="Close").click()
            await dialog.wait_for(state="detached")

        await asyncio.sleep(0.5)
        for _ in range(10):
            if not await dialog.is_visible():
                try:
                    await redeem_button_locator.click(force=True, timeout=3000)
                except TimeoutError:
                    pass
                if not await dialog.is_visible():
                    await redeem_button_locator.evaluate("el => el.click()")
            try:
                await dialog.wait_for(state="visible", timeout=2000)
                break
            except TimeoutError:
                await asyncio.sleep(1)
        else:
            raise Exception("Redeem dialog did not appear.")
        
        # Pick the character matching the requested slot (0-indexed)
        character_slot = f"Slot {character_idx - 1}"
        char_button = dialog.locator(".rf-char").filter(
            has_text=re.compile(f"{character_slot.lower()}$", re.IGNORECASE)
        )
        if await char_button.count() == 0:
            await dialog.get_by_role("button", name="Close").click()
            raise RedemptionFailedError(f"No matching character option found for index {character_idx} (expected {character_slot})")
        await char_button.click()

        # Set the quantity and let the UI recompute the purchase summary
        quantity_input = dialog.get_by_role("spinbutton")
        await quantity_input.fill(str(quantity))
        await quantity_input.blur()

        redeem_confirm = dialog.get_by_role("button", name="Redeem", exact=True)
        # The UI recomputes affordability server-side after the blur, so poll long enough
        for _ in range(40):
            if await redeem_confirm.is_disabled():
                await dialog.get_by_role("button", name="Close").click()
                await dialog.wait_for(state="detached")
                raise InsufficientPointsError(f"Insufficient points to redeem {quantity}x {item_name}")
            await asyncio.sleep(0.1)

        try:
            await redeem_confirm.click(timeout=10000)
            await dialog.wait_for(state="detached", timeout=10000)
            
        except Exception as e:
            # If the dialog is still open, it likely failed.
            if await dialog.is_visible():
                await dialog.get_by_role("button", name="Close").click()
                raise RedemptionFailedError(f"Redemption failed: {str(e)}")
            raise e


credentials = {}
if not os.path.exists('credentials.csv'):
    with open('credentials.csv', 'w') as f:
        f.write("username,password\n")
with open('credentials.csv', newline='') as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        credentials[row['username']] = row['password']

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        # browser = await p.chromium.launch()
        session = Session(browser)
        await session.start()
        login = "trimmedcube"
        await session.login(login, credentials[login], "loyalty")
        print(f"Loyalty Points: {await session.get_loyalty_points()}")
        await session.redeem_loyalty_item("Raid Scroll", 5, 2)
        print(f"Loyalty Points after: {await session.get_loyalty_points()}")
        await browser.close()        

if __name__ == "__main__":
    asyncio.run(main())
