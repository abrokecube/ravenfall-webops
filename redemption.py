import asyncio
import logging
from typing import List, Dict
from items import ITEMS
from session_manager import SessionManager
from browser_session import InsufficientPointsError, RedemptionFailedError

logger = logging.getLogger(__name__)

class RedemptionService:
    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager

    async def redeem_items(self, item_id: str, quantity: int, characters: List[Dict[str, str]]) -> Dict[str, int]:
        """
        Redeems items across a list of characters.
        characters: List of dicts with 'username' and 'id' (index).
        Returns a dict of {username: quantity_redeemed}
        """
        if item_id not in ITEMS:
            raise ValueError(f"Invalid item ID: {item_id}")
        
        item = ITEMS[item_id]
        remaining_quantity = quantity
        results = {}

        for char_info in characters:
            if remaining_quantity <= 0:
                break

            username = char_info.get('username')
            # Assuming 'id' is the character index as per user confirmation
            try:
                char_idx = int(char_info.get('id', 1))
            except (ValueError, TypeError):
                char_idx = 1

            if not username:
                continue

            redeemed_for_char = 0
            
            try:
                session = await self.session_manager.get_session(username)
                
                # Loop to redeem as much as possible/needed for this character
                while remaining_quantity > 0:
                    try:
                        points = await session.get_loyalty_points()
                    except Exception as e:
                        logger.error(f"Failed to get points for {username}: {e}")
                        break

                    can_afford = points // item.cost
                    if can_afford <= 0:
                        logger.info(f"Character {username}#{char_idx} has insufficient points ({points}).")
                        break # Move to next character

                    amount_to_try = min(remaining_quantity, can_afford)
                    
                    # Halving strategy loop
                    redemption_success = False
                    halves = 0
                    while amount_to_try > 0 and halves < 3:
                        try:
                            logger.info(f"Redeeming {amount_to_try} {item.name}(s) for {username}#{char_idx}")
                            await session.redeem_loyalty_item(item.name, amount_to_try, char_idx)
                            
                            # Success
                            remaining_quantity -= amount_to_try
                            redeemed_for_char += amount_to_try
                            redemption_success = True
                            break # Break halving loop, continue outer loop to check points again
                        except (RedemptionFailedError, InsufficientPointsError):
                            logger.warning(f"Redemption of {amount_to_try} failed for {username}#{char_idx}. Retrying with half...")
                            amount_to_try //= 2
                            halves += 1
                        except Exception as e:
                            logger.error(f"Unexpected error redeeming for {username}#{char_idx}: {e}")
                            amount_to_try = 0 # Force break
                    
                    if not redemption_success:
                        # If we failed to redeem anything (even 1 item), stop for this character
                        logger.info(f"Stopping redemption for {username}#{char_idx} due to repeated failures.")
                        break

                await self.session_manager.release_session(username)
                
            except Exception as e:
                logger.error(f"Failed to process redemption for {username}: {e}")
            
            if redeemed_for_char > 0:
                results[f"{username}#{char_idx}"] = redeemed_for_char

        return results
