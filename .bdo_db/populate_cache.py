import json
import time
import random
from bdo import update_codex_cache, load_cache  # sau copiază funcțiile aici

ITEMS_FILE = "item_db_from_bdocodex.json"

def main():
    with open(ITEMS_FILE, "r", encoding="utf-8") as f:
        items = json.load(f)

    cache = load_cache()
    total = len(items)
    for idx, item in enumerate(items, 1):
        item_id = item["id"]
        name = item["name"]
        # Check cache first!
        if str(item_id) in cache and cache[str(item_id)].get("name") and cache[str(item_id)].get("image"):
            print(f"[{idx}/{total}] Already cached: {item_id} ({name}), skipping.")
            continue
        print(f"[{idx}/{total}] Updating cache for item ID {item_id} ({name})...")
        update_codex_cache(item_id)
        time.sleep(random.uniform(1, 2))  # delay only if we actually did a request
        # time.sleep(1)

    print("All done!")

if __name__ == "__main__":
    main()
