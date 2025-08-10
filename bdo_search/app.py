from flask import Flask, render_template, request
import json
import requests
from datetime import datetime
import pytz
import time
import cloudscraper
import os

# CACHE_FILE = os.path.expanduser("~/bdo_trading_post_arbitrage/bdo_search/item_cache.json")
CACHE_FILE = os.path.expanduser("~/bdo_trading_post_arbitrage/bdo_search/item_cache_garmoth.json")

# Cache local pentru orders (item_id_sid: {data, ts})
garmoth_cache = {}

app = Flask(__name__)

@app.template_filter('format_number')
def format_number_filter(value):
    try:
        return "{:,}".format(int(value))
    except (ValueError, TypeError):
        return value


@app.template_filter('format_timestamp_ro')
def format_timestamp_ro(timestamp):
    """Format a UNIX timestamp to Europe/Bucharest time."""
    try:
        timestamp = int(timestamp)
        tz = pytz.timezone('Europe/Bucharest')
        dt = datetime.fromtimestamp(timestamp, tz)
        return dt.strftime("%d-%m-%Y %H:%M:%S")
    except Exception as e:
        return f"Invalid timestamp: {timestamp}"

@app.template_filter('enh_name')
def enh_name(min_e, max_e, sid):
    acc_labels = ["Base", "PRI", "DUO", "TRI", "TET", "PEN"]
    gear_labels = ["+{}".format(i) for i in range(0, 16)] + ["PRI", "DUO", "TRI", "TET", "PEN"]
    if min_e == max_e and min_e < len(acc_labels) and max_e <= 5:
        return acc_labels[min_e]
    elif min_e == max_e and min_e < len(gear_labels):
        return gear_labels[min_e]
    else:
        return f"{min_e} to {max_e}"

def sort_enhancements(market_list):
    # Sort by minEnhance, then sid as fallback
    return sorted(market_list, key=lambda x: (x.get("minEnhance", 0), x.get("sid", 0)))

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

def get_orders_from_garmoth_api(item_id, sub_key, region="eu", cache_time=10):
    """
    Fetch orders from Garmoth API for a given item_id and sub_key (enhancement level).
    Returns dict: {"orders": [...], "fetch_time": ..., "info": {...}}
    """
    key = f"{item_id}_{sub_key}"
    now = time.time()
    if key in garmoth_cache:
        entry = garmoth_cache[key]
        if now - entry["ts"] < cache_time:
            return {**entry["data"], "fetch_time": 0}

    url = f"https://garmoth.com/api/market/bidding-info-list?region={region}&main_key={item_id}&sub_key={sub_key}"
    scraper = cloudscraper.create_scraper()
    t0 = time.time()
    try:
        response = scraper.get(url, timeout=10)
        data = response.json()
    except Exception:
        return {"orders": [], "fetch_time": -1, "info": None}
    t1 = time.time()

    orders = []
    if "bidding" in data and isinstance(data["bidding"], list):
        for order in data["bidding"]:
            if len(order) == 3:
                sellers, price, buyers = order
                orders.append({
                    "sellers": sellers,
                    "price": price,
                    "buyers": buyers
                })
    fetch_time = round(t1 - t0, 3)
    result = {"orders": orders, "info": data.get("info")}
    garmoth_cache[key] = {"data": result, "ts": now}
    return {**result, "fetch_time": fetch_time}

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
    enhancement_details = None

    cache = None
    try:
        cache = load_cache()
    except FileNotFoundError:
        error = "item_cache.json not found! Please generate or copy it first."
        return render_template("index.html", result=None, error=error, query="", matches=None, total_items=0)

    total_items = len(cache)

    # POST: search
    if request.method == "POST":
        query = request.form.get("item_name", "").strip()
        if not query:
            error = "Please enter an item name."
        else:
            if query.isdigit() and query in cache:
                item_id = query
                item_info = cache[item_id]
                market_info = get_market_info(item_id)
                market_info = ensure_market_list(market_info)
                market_info = sort_enhancements(market_info)
                if not market_info:
                    error = "Could not fetch market info."
                else:
                    # Check if there's only one enhancement level with 0 to 0
                    if len(market_info) == 1 and market_info[0].get("minEnhance") == 0 and market_info[0].get("maxEnhance") == 0:
                        sid = market_info[0].get("sid")
                        orders = get_orders_from_garmoth_api(item_id, sid)
                        enhancement_details = {
                            "item_id": item_id,
                            "item_name": item_info.get("name"),
                            "item_image": item_info.get("image"),
                            "enhancement": market_info[0],
                            "orders": orders
                        }
                    else:
                        result = {
                            "item_id": item_id,
                            "item_name": item_info.get("name"),
                            "item_image": item_info.get("image"),
                            "market": market_info
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
                    market_info = sort_enhancements(market_info)
                    if not market_info:
                        error = "Could not fetch market info."
                    else:
                        if len(market_info) == 1 and market_info[0].get("minEnhance") == 0 and market_info[0].get("maxEnhance") == 0:
                            sid = market_info[0].get("sid")
                            orders = get_orders_from_garmoth_api(found_id, sid)
                            enhancement_details = {
                                "item_id": found_id,
                                "item_name": item_info.get("name"),
                                "item_image": item_info.get("image"),
                                "enhancement": market_info[0],
                                "orders": orders
                            }
                        else:
                            result = {
                                "item_id": found_id,
                                "item_name": item_info.get("name"),
                                "item_image": item_info.get("image"),
                                "market": market_info
                            }
                else:
                    matches = found_items

        return render_template("index.html", result=result, error=error, query=query, matches=matches, total_items=total_items, enhancement_details=enhancement_details)

    # GET cu item_id și sid (enhancement level)
    item_id_param = request.args.get("item_id")
    sid_param = request.args.get("sid")
    if item_id_param and sid_param:
        if item_id_param in cache:
            item_info = cache[item_id_param]
            market_info = get_market_info(item_id_param)
            market_info = ensure_market_list(market_info)
            market_info = sort_enhancements(market_info)
            enhancement = None
            for entry in market_info:
                if str(entry.get("sid")) == str(sid_param):
                    enhancement = entry
                    break
            if enhancement:
                orders = get_orders_from_garmoth_api(item_id_param, int(sid_param))
                enhancement_details = {
                    "item_id": item_id_param,
                    "item_name": item_info.get("name"),
                    "item_image": item_info.get("image"),
                    "enhancement": enhancement,
                    "orders": orders
                }
            else:
                error = "Enhancement level not found."
        return render_template("index.html", enhancement_details=enhancement_details, error=error, query="", matches=None, total_items=total_items)

    # GET cu doar item_id: afișează lista de enhancement-uri (fără orders)
    if item_id_param:
        if item_id_param in cache:
            item_info = cache[item_id_param]
            market_info = get_market_info(item_id_param)
            market_info = ensure_market_list(market_info)
            market_info = sort_enhancements(market_info)
            if len(market_info) == 1 and market_info[0].get("minEnhance") == 0 and market_info[0].get("maxEnhance") == 0:
                sid = market_info[0].get("sid")
                orders = get_orders_from_garmoth_api(item_id_param, sid)
                enhancement_details = {
                    "item_id": item_id_param,
                    "item_name": item_info.get("name"),
                    "item_image": item_info.get("image"),
                    "enhancement": market_info[0],
                    "orders": orders
                }
                return render_template("index.html", enhancement_details=enhancement_details, error=error, query="", matches=None, total_items=total_items)
            else:
                result = {
                    "item_id": item_id_param,
                    "item_name": item_info.get("name"),
                    "item_image": item_info.get("image"),
                    "market": market_info
                }
        return render_template("index.html", result=result, error=error, query="", matches=None, total_items=total_items)

    # Default: search form
    return render_template("index.html", result=None, error=error, query=query, matches=matches, total_items=total_items)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8520, debug=True)
