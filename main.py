from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import logging
import uvicorn
from contextlib import asynccontextmanager
import os

from session_manager import SessionManager
from redemption import RedemptionService

from dotenv import load_dotenv


with open('pid', 'w') as f:
    f.write(str(os.getpid()))
    
load_dotenv()

logger = logging.getLogger(__name__)

session_manager = SessionManager()
redemption_service = RedemptionService(session_manager)

@asynccontextmanager
async def lifespan(app: FastAPI):
    headless = os.getenv("HEADLESS", "true") not in ["false", "0", "no"]
    if not headless:
        print("running with browser windows")
    await session_manager.start(headless=headless)
    yield
    await session_manager.stop()

app = FastAPI(lifespan=lifespan)

class Character(BaseModel):
    username: str
    id: str # Character index

class RedemptionRequest(BaseModel):
    item_id: str
    quantity: int
    characters: List[Character]

class LoyaltyPointsRequest(BaseModel):
    usernames: List[str]

@app.post("/redeem")
async def redeem_items(request: RedemptionRequest):
    try:
        # Convert Pydantic models to dicts for the service
        chars_dicts = [c.model_dump() for c in request.characters]
        results = await redemption_service.redeem_items(request.item_id, request.quantity, chars_dicts)
        return {"status": "success", "redeemed": results}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Redemption failed")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/loyalty/points")
async def get_loyalty_points(request: LoyaltyPointsRequest):
    import asyncio
    
    # Semaphore to limit concurrent processing of users
    # Max 3 sessions as per requirement
    sem = asyncio.Semaphore(3)
    
    async def fetch_points(username: str):
        async with sem:
            try:
                session = await session_manager.get_session(username)
                points = await session.get_loyalty_points()
                await session_manager.release_session(username)
                return points
            except Exception as e:
                logger.error(f"Failed to get points for {username}: {e}")
                # Ensure we release the session even on error
                # Note: get_session might fail, in which case we don't need to release.
                # But if get_session succeeded and get_loyalty_points failed, we must release.
                # We can check if username is in active_sessions or just call release safely.
                # session_manager.release_session handles checking.
                await session_manager.release_session(username)
                return -1

    tasks = [fetch_points(u) for u in request.usernames]
    results = await asyncio.gather(*tasks)
    total_points = sum(results)
    
    return {"status": "success", "total_points": total_points, "breakdown": dict(zip(request.usernames, results))}

def main():
    """
    Entry point for the Process Watcher application.
    Starts the Uvicorn server with the FastAPI app.
    """
    # The monitor thread is already started when importing 'app' from 'api'
    # because of the module-level code in api.py.
    uvicorn.run(app, host=os.getenv("SERVER_HOST", "0.0.0.0"), port=int(os.getenv("SERVER_PORT", 7102)))

if __name__ == "__main__":
    main()