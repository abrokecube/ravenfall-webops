from dataclasses import dataclass

@dataclass
class Item:
    id: str
    name: str
    cost: int

ITEMS = {
    "raid_scroll": Item("raid_scroll", "Raid Scroll", 100),
    "dungeon_scroll": Item("dungeon_scroll", "Dungeon Scroll", 150),
    "exp_multiplier_scroll": Item("exp_multiplier_scroll", "Exp Multiplier Scroll", 1000),
}
