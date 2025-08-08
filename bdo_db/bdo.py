import requests
from bs4 import BeautifulSoup
import json
import os
import sys
from datetime import datetime
import pytz
import html

CACHE_FILE = "item_cache.json"

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def update_codex_cache(item_id):
    cache = load_cache()
    if str(item_id) in cache and cache[str(item_id)].get("name") and cache[str(item_id)].get("image"):
        return  # Already cached
    url = f"https://bdocodex.com/us/item/{item_id}/"
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        script = soup.find("script", type="application/ld+json")
        if script:
            data = json.loads(script.string)
            item_name = data.get("name", "").strip()
            image = data.get("image", "").strip()
            if image and image.startswith("/"):
                image = "https://bdocodex.com" + image
            info = {"name": item_name, "image": image}
        else:
            item_name = ""
            image = ""
            meta_og_title = soup.find("meta", property="og:title")
            if meta_og_title and meta_og_title.get("content"):
                item_name = meta_og_title["content"].strip()
            meta_og_image = soup.find("meta", property="og:image")
            if meta_og_image and meta_og_image.get("content"):
                image = meta_og_image["content"].strip()
            info = {"name": item_name, "image": image}
        if info["name"] and info["image"]:
            cache[str(item_id)] = info
            save_cache(cache)
    except Exception as e:
        print(f"Failed to update cache for item {item_id}: {e}")

def format_timestamp_ro(timestamp):
    try:
        timestamp = int(timestamp)
        tz = pytz.timezone('Europe/Bucharest')
        dt = datetime.fromtimestamp(timestamp, tz)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        return f"Invalid timestamp: {timestamp}"

def get_market_item(item_id: int, region: str = "EU"):
    region_map = {
        "EU": "eu",
        "NA": "na"
    }
    region_api = region_map.get(region.upper(), "eu")
    url = f"https://api.arsha.io/v2/{region_api}/item?id={item_id}&lang=en"

    try:
        response = requests.get(url)
        response.raise_for_status()

        print("Raw JSON:", response.text[:300])

        data = response.json()
        if not data or not isinstance(data, dict):
            print("Invalid or empty result.")
            return

        print("=== Market Item Info ===")
        print("Item ID:", data.get("id"))
        print("Item Name:", data.get("name"))
        print("Enhancement Range:", f"{data.get('minEnhance', 'N/A')} to {data.get('maxEnhance', 'N/A')}")
        print("Base Price:", data.get("basePrice", "N/A"))
        print("Current Stock:", data.get("currentStock", "N/A"))
        print("Total Trades:", data.get("totalTrades", "N/A"))
        print("Price Cap (Min):", data.get("priceMin", "N/A"))
        print("Price Cap (Max):", data.get("priceMax", "N/A"))
        print("Last Sale Price:", data.get("lastSoldPrice", "N/A"))
        last_sold_time = data.get("lastSoldTime")
        if last_sold_time:
            print("Last Sale Time:", format_timestamp_ro(last_sold_time))
        else:
            print("Last Sale Time: N/A")
        print("========================")

        # Update Codex cache after displaying
        update_codex_cache(item_id)

    except requests.exceptions.RequestException as e:
        print("Request failed:", e)
    except requests.exceptions.JSONDecodeError:
        print("Failed to decode JSON response.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 bdo.py <item_id>")
        print("Example: python3 bdo.py 16001")
        sys.exit(1)

    item_id = sys.argv[1]
    if not item_id.isdigit():
        print("Item ID must be a number!")
        sys.exit(1)

    get_market_item(int(item_id))
