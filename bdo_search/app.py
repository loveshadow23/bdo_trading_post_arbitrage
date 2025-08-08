from flask import Flask, render_template, request
import json
import requests
from datetime import datetime
import pytz

CACHE_FILE = "item_cache.json"

app = Flask(__name__)

@app.template_filter('format_number')
def format_number_filter(value):
    """Format numbers with thousands separator (comma)."""
    try:
        return "{:,}".format(int(value)).replace(",", ",")
    except (ValueError, TypeError):
        return value

def load_cache():
    """Load the item cache from file."""
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def search_items_by_name(query, cache):
    """Return a list of items (id, name, image) whose name contains the query (case-insensitive)."""
    query_lc = query.strip().lower()
    results = []
    for item_id, info in cache.items():
        name = info.get("name", "")
        if query_lc in name.lower():
            results.append({
                "id": item_id,
                "name": name,
                "image": info.get("image")
            })
    return results

def format_timestamp_ro(timestamp):
    """Format a UNIX timestamp to Europe/Bucharest time."""
    try:
        timestamp = int(timestamp)
        tz = pytz.timezone('Europe/Bucharest')
        dt = datetime.fromtimestamp(timestamp, tz)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        return f"Invalid timestamp: {timestamp}"

def get_market_info(item_id, region="EU"):
    """Query arsha.io for market info for a given item_id."""
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

def get_orders_info(item_id, sid, region="EU"):
    """Query arsha.io for orders info for a given item_id and sid."""
    region_map = {
        "EU": "eu",
        "NA": "na"
    }
    region_api = region_map.get(region.upper(), "eu")
    url = f"https://api.arsha.io/v2/{region_api}/orders?id={item_id}&sid={sid}&lang=en"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data
    except Exception as e:
        return None

def ensure_market_list(market_info):
    """
    Always return a list of dicts, whether the API returned a dict or a list of dicts.
    """
    if isinstance(market_info, dict):
        return [market_info]
    elif isinstance(market_info, list):
        return [x for x in market_info if isinstance(x, dict)]
    else: 
        return []

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    query = ""
    matches = None
    total_items = 0

    # Handle POST (search form). On POST, ignore any item_id from GET!
    if request.method == "POST":
        query = request.form.get("item_name", "").strip()
        if not query:
            error = "Please enter an item name."
        else:
            try:
                cache = load_cache()
            except FileNotFoundError:
                error = "item_cache.json not found! Please generate or copy it first."
                return render_template("index.html", result=None, error=error, query=query, matches=None, total_items=0)
            total_items = len(cache)
            # Accept numeric ID as direct search
            if query.isdigit() and query in cache:
                item_info = cache[query]
                market_info = get_market_info(query)
                market_info = ensure_market_list(market_info)
                if not market_info:
                    error = "Could not fetch market info."
                else:
                    result = {
                        "item_id": query,
                        "item_name": item_info.get("name"),
                        "item_image": item_info.get("image"),
                        "market": [
                            {
                                "Enhancement Range": f"{entry.get('minEnhance', 'N/A')} to {entry.get('maxEnhance', 'N/A')}",
                                "Base Price": entry.get("basePrice", "N/A"),
                                "Current Stock": entry.get("currentStock", "N/A"),
                                "Total Trades": entry.get("totalTrades", "N/A"),
                                "Price Cap (Min)": entry.get("priceMin", "N/A"),
                                "Price Cap (Max)": entry.get("priceMax", "N/A"),
                                "Last Sale Price": entry.get("lastSoldPrice", "N/A"),
                                "Last Sale Time": format_timestamp_ro(entry.get("lastSoldTime")) if entry.get("lastSoldTime") else "N/A",
                                "sid": entry.get("sid", "N/A"),
                                "orders": get_orders_info(entry.get("id"), entry.get("sid"))
                            }
                            for entry in ensure_market_list(market_info)
                        ]
                    }
            else:
                found_items = search_items_by_name(query, cache)
                if not found_items:
                    error = f"Item '{query}' not found in cache."
                elif len(found_items) == 1:
                    found_id = found_items[0]["id"]
                    item_info = cache[found_id]
                    market_info = get_market_info(found_id)
                    market_info = ensure_market_list(market_info)
                    if not market_info:
                        error = "Could not fetch market info."
                    else:
                        result = {
                            "item_id": found_id,
                            "item_name": item_info.get("name"),
                            "item_image": item_info.get("image"),
                            "market": [
                                {
                                    "Enhancement Range": f"{entry.get('minEnhance', 'N/A')} to {entry.get('maxEnhance', 'N/A')}",
                                    "Base Price": entry.get("basePrice", "N/A"),
                                    "Current Stock": entry.get("currentStock", "N/A"),
                                    "Total Trades": entry.get("totalTrades", "N/A"),
                                    "Price Cap (Min)": entry.get("priceMin", "N/A"),
                                    "Price Cap (Max)": entry.get("priceMax", "N/A"),
                                    "Last Sale Price": entry.get("lastSoldPrice", "N/A"),
                                    "Last Sale Time": format_timestamp_ro(entry.get("lastSoldTime")) if entry.get("lastSoldTime") else "N/A",
                                    "sid": entry.get("sid", "N/A"),
                                    "orders": get_orders_info(entry.get("id"), entry.get("sid"))
                                }
                                for entry in ensure_market_list(market_info)
                            ]
                        }
                else:
                    matches = found_items

        return render_template("index.html", result=result, error=error, query=query, matches=matches, total_items=total_items)

    # If GET with ?item_id=..., show details for that item
    item_id_param = request.args.get("item_id")
    if item_id_param:
        try:
            cache = load_cache()
        except FileNotFoundError:
            error = "item_cache.json not found! Please generate or copy it first."
            return render_template("index.html", result=None, error=error, query="", matches=None, total_items=0)
        total_items = len(cache)
        if item_id_param in cache:
            item_info = cache[item_id_param]
            market_info = get_market_info(item_id_param)
            market_info = ensure_market_list(market_info)
            if not market_info:
                error = "Could not fetch market info. Probably the item does not exist on Market right now."
            else:
                result = {
                    "item_id": item_id_param,
                    "item_name": item_info.get("name"),
                    "item_image": item_info.get("image"),
                    "market": [
                        {
                            "Enhancement Range": f"{entry.get('minEnhance', 'N/A')} to {entry.get('maxEnhance', 'N/A')}",
                            "Base Price": entry.get("basePrice", "N/A"),
                            "Current Stock": entry.get("currentStock", "N/A"),
                            "Total Trades": entry.get("totalTrades", "N/A"),
                            "Price Cap (Min)": entry.get("priceMin", "N/A"),
                            "Price Cap (Max)": entry.get("priceMax", "N/A"),
                            "Last Sale Price": entry.get("lastSoldPrice", "N/A"),
                            "Last Sale Time": format_timestamp_ro(entry.get("lastSoldTime")) if entry.get("lastSoldTime") else "N/A",
                            "sid": entry.get("sid", "N/A"),
                            "orders": get_orders_info(entry.get("id"), entry.get("sid"))
                        }
                        for entry in ensure_market_list(market_info)
                    ]
                }
        return render_template("index.html", result=result, error=error, query="", matches=None, total_items=total_items)

    # If neither POST nor GET with item_id, show search form only
    return render_template("index.html", result=None, error=error, query=query, matches=matches, total_items=total_items)

if __name__ == "__main__":
    app.run(debug=True)
