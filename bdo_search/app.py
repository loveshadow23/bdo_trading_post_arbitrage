from flask import Flask, render_template, request
import json
import requests
from datetime import datetime
import pytz

CACHE_FILE = "item_cache.json"

app = Flask(__name__)

def load_cache():
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def find_id_by_name(item_name, cache):
    name_lc = item_name.strip().lower()
    for item_id, info in cache.items():
        if info.get("name", "").strip().lower() == name_lc:
            return item_id
    return None

def format_timestamp_ro(timestamp):
    try:
        timestamp = int(timestamp)
        tz = pytz.timezone('Europe/Bucharest')
        dt = datetime.fromtimestamp(timestamp, tz)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        return f"Invalid timestamp: {timestamp}"

def get_market_info(item_id, region="EU"):
    region_map = {
        "EU": "eu",
        "NA": "na"
    }
    region_api = region_map.get(region.upper(), "eu")
    url = f"https://api.arsha.io/v2/{region_api}/item?id={item_id}&lang=en"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data
    except Exception as e:
        return None

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    query = ""
    if request.method == "POST":
        query = request.form.get("item_name", "").strip()
        if not query:
            error = "Please enter an item name."
        else:
            cache = load_cache()
            found_id = find_id_by_name(query, cache)
            if not found_id:
                error = f"Item '{query}' not found in cache."
            else:
                item_info = cache[found_id]
                market_info = get_market_info(found_id)
                if not market_info:
                    error = "Could not fetch market info."
                else:
                    result = {
                        "item_id": found_id,
                        "item_name": item_info.get("name"),
                        "item_image": item_info.get("image"),
                        "market": {
                            "Enhancement Range": f"{market_info.get('minEnhance', 'N/A')} to {market_info.get('maxEnhance', 'N/A')}",
                            "Base Price": market_info.get("basePrice", "N/A"),
                            "Current Stock": market_info.get("currentStock", "N/A"),
                            "Total Trades": market_info.get("totalTrades", "N/A"),
                            "Price Cap (Min)": market_info.get("priceMin", "N/A"),
                            "Price Cap (Max)": market_info.get("priceMax", "N/A"),
                            "Last Sale Price": market_info.get("lastSoldPrice", "N/A"),
                            "Last Sale Time": format_timestamp_ro(market_info.get("lastSoldTime")) if market_info.get("lastSoldTime") else "N/A"
                        }
                    }
    return render_template("index.html", result=result, error=error, query=query)

if __name__ == "__main__":
    app.run(debug=True)
