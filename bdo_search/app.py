from flask import Flask, render_template, request, url_for
import json
import requests
from datetime import datetime
import pytz
import time
import cloudscraper
import os

CACHE_FILE = os.path.expanduser("~/bdo_trading_post_arbitrage/bdo_search/item_cache_garmoth.json")

# Cache for orders (item_id_sid: {data, ts})
garmoth_cache = {}

app = Flask(__name__)

@app.template_filter('format_number')
def format_number_filter(value):
    """Format numbers with thousands separator (comma)."""
    try:
        return "{:,}".format(int(value))
    except (ValueError, TypeError):
        return value

@app.template_filter('format_timestamp_ro')
def format_timestamp_ro(timestamp):
    """Format a UNIX timestamp to Europe/Bucharest time."""
    try:
        timestamp = int(timestamp)
        dt = datetime.fromtimestamp(timestamp, pytz.timezone('Europe/Bucharest'))
        return dt.strftime("%d-%m-%Y %H:%M:%S")
    except Exception:
        return f"Invalid timestamp: {timestamp}"

@app.template_filter('enh_name')
def enh_name(min_e, max_e, sid):
    acc_labels = ["Base", "PRI", "DUO", "TRI", "TET", "PEN"]
    gear_labels = [f"+{i}" for i in range(16)] + ["PRI", "DUO", "TRI", "TET", "PEN"]
    
    if min_e == max_e and min_e < len(acc_labels) and max_e <= 5:
        return acc_labels[min_e]
    elif min_e == max_e and min_e < len(gear_labels):
        return gear_labels[min_e]
    else:
        return f"{min_e} to {max_e}"

def load_cache():
    """Load the item cache from file."""
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def search_items_by_name(query, cache):
    """Return items whose name contains the query (case-insensitive)."""
    query_lc = query.strip().lower()
    return [
        {
            "id": item_id,
            "name": info.get("name", ""),
            "image": info.get("image")
        }
        for item_id, info in cache.items()
        if query_lc in info.get("name", "").lower()
    ]

def get_market_info(item_id, region="EU"):
    """Query arsha.io for market info for a given item_id."""
    region_api = {"EU": "eu", "NA": "na"}.get(region.upper(), "eu")
    url = f"https://api.arsha.io/v2/{region_api}/item?id={item_id}&lang=en"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None

def get_orders_from_garmoth_api(item_id, sub_key, region="eu", cache_time=10):
    """Fetch orders from Garmoth API for a given item_id and sub_key."""
    key = f"{item_id}_{sub_key}"
    now = time.time()
    
    # Check cache
    if key in garmoth_cache and now - garmoth_cache[key]["ts"] < cache_time:
        return {**garmoth_cache[key]["data"], "fetch_time": 0}

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
                orders.append({"sellers": sellers, "price": price, "buyers": buyers})
    
    result = {"orders": orders, "info": data.get("info")}
    garmoth_cache[key] = {"data": result, "ts": now}
    return {**result, "fetch_time": round(t1 - t0, 3)}

def ensure_market_list(market_info):
    """Always return a list of dicts from market info."""
    if isinstance(market_info, dict):
        return [market_info]
    elif isinstance(market_info, list):
        return [x for x in market_info if isinstance(x, dict)]
    else: 
        return []

def process_item_details(item_id, cache):
    """Process item details and market info."""
    if item_id not in cache:
        return None, "Item not found in cache."
    
    item_info = cache[item_id]
    market_info = get_market_info(item_id)
    market_info = ensure_market_list(market_info)
    market_info = sorted(market_info, key=lambda x: (x.get("minEnhance", 0), x.get("sid", 0)))
    
    if not market_info:
        return None, "Could not fetch market info."
    
    # Check if there's only one enhancement level with 0 to 0
    if len(market_info) == 1 and market_info[0].get("minEnhance") == 0 and market_info[0].get("maxEnhance") == 0:
        sid = market_info[0].get("sid")
        orders = get_orders_from_garmoth_api(item_id, sid)
        return {
            "enhancement_details": {
                "item_id": item_id,
                "item_name": item_info.get("name"),
                "item_image": item_info.get("image"),
                "enhancement": market_info[0],
                "orders": orders
            }
        }, None
    else:
        return {
            "result": {
                "item_id": item_id,
                "item_name": item_info.get("name"),
                "item_image": item_info.get("image"),
                "market": market_info
            }
        }, None

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    query = ""
    matches = None
    enhancement_details = None
    
    cache = load_cache()
    total_items = len(cache)
    
    if not cache:
        error = "Item cache not found! Please generate or copy it first."
        return render_template("index.html", error=error, total_items=0)

    # Handle POST request (search)
    if request.method == "POST":
        query = request.form.get("item_name", "").strip()
        if not query:
            error = "Please enter an item name."
        else:
            # Direct ID lookup
            if query.isdigit() and query in cache:
                data, error = process_item_details(query, cache)
                if data:
                    result = data.get("result")
                    enhancement_details = data.get("enhancement_details")
            else:
                # Name search
                found_items = search_items_by_name(query, cache)
                if not found_items:
                    error = f"Item '{query}' not found in cache."
                elif len(found_items) == 1:
                    data, error = process_item_details(found_items[0]["id"], cache)
                    if data:
                        result = data.get("result")
                        enhancement_details = data.get("enhancement_details")
                else:
                    matches = found_items

    # Handle GET with item_id and sid
    item_id_param = request.args.get("item_id")
    sid_param = request.args.get("sid")
    
    if item_id_param and sid_param and item_id_param in cache:
        item_info = cache[item_id_param]
        market_info = get_market_info(item_id_param)
        market_info = ensure_market_list(market_info)
        market_info = sorted(market_info, key=lambda x: (x.get("minEnhance", 0), x.get("sid", 0)))
        
        enhancement = next((entry for entry in market_info if str(entry.get("sid")) == str(sid_param)), None)
        
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
    
    # Handle GET with only item_id
    elif item_id_param and item_id_param in cache:
        data, error = process_item_details(item_id_param, cache)
        if data:
            result = data.get("result")
            enhancement_details = data.get("enhancement_details")

    return render_template(
        "index.html", 
        result=result, 
        error=error, 
        query=query, 
        matches=matches, 
        total_items=total_items, 
        enhancement_details=enhancement_details
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8520, debug=True)
