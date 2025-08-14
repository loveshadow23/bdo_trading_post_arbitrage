import requests
import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, jsonify
from huffman_binary_decode import unpack
import logging
from logging.handlers import RotatingFileHandler
from requests.adapters import HTTPAdapter
try:
    from urllib3.util import Retry
except Exception:
    Retry = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CACHE_FILE = os.path.join(BASE_DIR, "item_cache_garmoth.json")
CACHE_FILE = os.getenv("BDO_ITEM_CACHE", DEFAULT_CACHE_FILE)
API_BASE_URL = os.getenv("BDO_API_BASE_URL", "https://eu-trade.naeu.playblackdesert.com")
TIMEZONE_NAME = os.getenv("BDO_TIMEZONE", "Europe/Bucharest")
DEFAULT_ITEMS_PER_PAGE = int(os.getenv("BDO_ITEMS_PER_PAGE", "25"))
HTTP_TIMEOUT = float(os.getenv("BDO_HTTP_TIMEOUT", "10"))
FIELDS = [
    "item_id", "enhancement_min", "enhancement_max", "base_price", "current_stock",
    "total_trades", "price_hardcap_min", "price_hardcap_max", "last_sale_price", "last_sale_time"
]

app = Flask(__name__)

# Logging configuration
LOG_LEVEL = os.getenv("BDO_LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("BDO_LOG_FILE", os.path.join(BASE_DIR, "bdo_search.log"))
logger = logging.getLogger("bdo")
logger.setLevel(LOG_LEVEL)
_fmt = logging.Formatter("[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
try:
    _fh = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)
except Exception:
    # Fallback to console-only if file handler cannot be used
    pass
_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
logger.addHandler(_ch)

# Timezone configuration
try:
    TZ = ZoneInfo(TIMEZONE_NAME)
except Exception:
    TZ = ZoneInfo("UTC")
    logger.warning("Invalid timezone %s; using UTC", TIMEZONE_NAME)

# HTTP session with retries/timeouts
def _init_http_session():
    s = requests.Session()
    if Retry is not None:
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "POST"]),
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    else:
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"Content-Type": "application/json", "User-Agent": "BlackDesert"})
    return s

session = _init_http_session()

# Simple hotlist cache (TTL configurable)
HOTLIST_TTL = int(os.getenv("BDO_HOTLIST_TTL", "30"))
_hotlist_cache = {"ts": 0, "items": []}

# Default items per page (configurable)
app.config["ITEMS_PER_PAGE"] = DEFAULT_ITEMS_PER_PAGE

# Cache la nivel de proces pentru baza de date iteme
_item_db_cache = None
def get_item_db():
    """Load item DB JSON once per process, with fallback and logging."""
    global _item_db_cache
    if _item_db_cache is None:
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                _item_db_cache = json.load(f)
                logger.info("Loaded item DB from %s (%d items)", CACHE_FILE, len(_item_db_cache))
        except FileNotFoundError:
            alt_path = os.path.join(BASE_DIR, "item_cache_codex.json")
            try:
                with open(alt_path, encoding="utf-8") as f:
                    _item_db_cache = json.load(f)
                    logger.info("Loaded fallback item DB from %s (%d items)", alt_path, len(_item_db_cache))
            except Exception:
                logger.exception("Failed to load item DB from %s and fallback", CACHE_FILE)
                _item_db_cache = {}
        except Exception:
            logger.exception("Error reading item DB from %s", CACHE_FILE)
            _item_db_cache = {}
    return _item_db_cache

@app.template_filter('format_number')
def format_number_filter(value):
    try:
        return "{:,}".format(int(value))
    except Exception:
        return value

@app.template_filter('enh_name')
def enh_name(min_e, max_e, item_id=None):
    # Determine if this is an accessory (only uses PRI-PEN system)
    # Accessories typically have enhancement levels from 0-5 or 1-5
    is_accessory = max_e <= 5 
    
    if min_e == max_e:
        if min_e == 0:
            return ""
            
        # For accessories that only use PRI-PEN system, map directly
        if is_accessory and 1 <= min_e <= 5:
            acc_labels = ["", "PRI (I)", "DUO (II)", "TRI (III)", "TET (IV)", "PEN (V)"]
            return acc_labels[min_e]
        
        # For standard items that use +1 to +15 system
        if 1 <= min_e <= 15:
            return f"+{min_e}"
            
        # For standard items that continue to PRI-PEN after +15
        acc_labels = ["", "PRI (I)", "DUO (II)", "TRI (III)", "TET (IV)", "PEN (V)"]
        if 16 <= min_e <= 20:
            return acc_labels[min_e - 15]
    
    return f"{min_e} to {max_e}"

def unix_to_ro_time(ts):
    """Convert unix timestamp to configured timezone string DD.MM.YYYY HH:MM."""
    try:
        return datetime.fromtimestamp(ts, tz=TZ).strftime("%d.%m.%Y %H:%M")
    except Exception:
        logger.exception("Failed to convert timestamp: %r", ts)
        return "-"

def find_items(query, item_db):
    q = query.lower()
    results = []
    # Caută după id exact
    if q in item_db:
        results.append((q, item_db[q]))
    # Caută după nume exact sau parțial
    for k, v in item_db.items():
        name = v.get("name", "").lower()
        if name == q or q in name:
            if (k, v) not in results:
                results.append((k, v))
    return results

def fetch_market_data(item_id):
    """Fetch per-item market data."""
    payload = {"keyType": 0, "mainKey": int(item_id)}
    url = f"{API_BASE_URL}/Trademarket/GetWorldMarketSubList"
    logger.debug("Fetching market data for item_id=%s", item_id)
    r = session.post(url, json=payload, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return parse_market_data(r.json().get("resultMsg", ""))

def fetch_bidding_info(item_id, sub_key):
    """Fetch bidding info for a given item and subKey (enhancement level)."""
    payload = {"keyType": 0, "mainKey": int(item_id), "subKey": int(sub_key)}
    url = f"{API_BASE_URL}/Trademarket/GetBiddingInfoList"
    logger.debug("Fetching bidding info for item_id=%s sub_key=%s", item_id, sub_key)
    r = session.post(url, json=payload, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    try:
        decoded = unpack(r.content)
        return parse_bidding_info(decoded)
    except Exception:
        try:
            return parse_bidding_info(r.json().get("resultMsg", ""))
        except Exception:
            logger.exception("Failed to decode bidding info for item_id=%s sub_key=%s", item_id, sub_key)
            return []

def fetch_hotlist():
    """Fetch & parse hot items from BDO HotList API (with TTL cache)."""
    now = time.time()
    # Return cached if fresh
    if _hotlist_cache["items"] and (now - _hotlist_cache["ts"]) < HOTLIST_TTL:
        return _hotlist_cache["items"]

    url = f"{API_BASE_URL}/Trademarket/GetWorldMarketHotList"
    logger.debug("Fetching hotlist from %s", url)
    resp = session.post(url, data="", timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    decoded = unpack(resp.content)
    if isinstance(decoded, bytes):
        decoded = decoded.decode('utf-8')
    items = []
    for entry in decoded.strip("|").split("|"):
        values = entry.split("-")
        if len(values) == 12:
            try:
                items.append({
                    "item_id": values[0],
                    "enh_min": int(values[1]),
                    "enh_max": int(values[2]),
                    "base_price": int(values[3]),
                    "stock": int(values[4]),
                    "total_trades": int(values[5]),
                    "price_dir": int(values[6]),   # 1 = down, 2 = up
                    "price_change": int(values[7]),
                    "price_min": int(values[8]),
                    "price_max": int(values[9]),
                    "last_sale_price": int(values[10]),
                    "last_sale_time": int(values[11]),
                    "last_sale_time_ro": unix_to_ro_time(int(values[11])),
                })
            except Exception:
                logger.debug("Skipping invalid hotlist entry: %r", entry)
    _hotlist_cache["items"] = items
    _hotlist_cache["ts"] = now
    return items

def parse_bidding_info(decoded_str):
    """Parse bidding info pipe string into list of dicts."""
    if not decoded_str:
        return []
    result = []
    for entry in decoded_str.strip("|").split("|"):
        values = entry.split("-")
        if len(values) == 3:
            try:
                result.append({
                    "price": int(values[0]),
                    "sell_orders": int(values[1]),
                    "buy_orders": int(values[2])
                })
            except Exception:
                logger.debug("Skipping invalid bidding entry: %r", entry)
    return result

def parse_market_data(result_msg):
    """Parse market data result string returned by the API."""
    if not result_msg:
        return []
    items = []
    for entry in result_msg.strip("|").split("|"):
        values = entry.split("-")
        if len(values) == 10:
            try:
                item = {FIELDS[i]: int(values[i]) for i in range(10)}
                item["last_sale_time_ro"] = unix_to_ro_time(item["last_sale_time"])
                items.append(item)
            except Exception:
                logger.debug("Skipping invalid market entry: %r", entry)
    return items

def get_market_and_bidding(item_id, enh_min=None, enh_max=None):
    market_data = fetch_market_data(item_id)
    if enh_min is not None and enh_max is not None:
        market_data = [item for item in market_data if item["enhancement_min"] == enh_min and item["enhancement_max"] == enh_max]
    for item in market_data:
        sub_key = item["enhancement_max"]
        item["bidding_info"] = fetch_bidding_info(item_id, sub_key)
        if item["bidding_info"]:
            item["bidding_info"].sort(key=lambda x: x["price"], reverse=True)
    return market_data

 

@app.route("/", methods=["GET", "POST"])
def index():
    results = details = enh_list = None
    query = ""
    hotlist = None
    page = request.args.get('page', 1, type=int)
    items_per_page = app.config["ITEMS_PER_PAGE"]  # Get from app config
    
    if request.method == "POST":
        query = request.form.get("query", "").strip()
        if query:
            item_db = get_item_db()
            matches = find_items(query, item_db)
            if matches:
                if len(matches) == 1:
                    item_id, item_info = matches[0]
                    market_data = fetch_market_data(item_id)
                    if len(market_data) > 1:
                        enh_list = [
                            {
                                "id": item_id,
                                "name": item_info.get("name"),
                                "image": item_info.get("image"),
                                "enhancement_min": item["enhancement_min"],
                                "enhancement_max": item["enhancement_max"]
                            }
                            for item in market_data
                        ]
                    else:
                        details = {
                            "id": item_id,
                            "name": item_info.get("name"),
                            "image": item_info.get("image"),
                            "market_data": get_market_and_bidding(item_id)
                        }
                else:
                    results = [
                        {
                            "id": item_id,
                            "name": item_info.get("name"),
                            "image": item_info.get("image")
                        }
                        for item_id, item_info in matches
                    ]
            else:
                results = "not_found"
    # Dacă nu e căutare, afișează hotlist pe landing page
    if not query and not results and not details and not enh_list:
        item_db = get_item_db()
        try:
            all_hotlist = fetch_hotlist()
        except Exception:
            logger.exception("Failed to fetch hotlist for landing page")
            all_hotlist = []
        for item in all_hotlist:
            info = item_db.get(str(item["item_id"]), {})
            item["name"] = info.get("name", f"ID {item['item_id']}")
            item["image"] = info.get("image", "")
        all_hotlist.sort(key=lambda x: x["total_trades"], reverse=True)
        
        # Calculate pagination
        total_items = len(all_hotlist)
        total_pages = (total_items + items_per_page - 1) // items_per_page
        page = min(max(page, 1), total_pages)  # Ensure page is within valid range
        
        # Get items for current page
        start_idx = (page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, total_items)
        hotlist = all_hotlist[start_idx:end_idx]
        
        return render_template(
            "index.html",
            results=results,
            details=details,
            enh_list=enh_list,
            query=query,
            hotlist=hotlist,
            page=page,
            total_pages=total_pages,
            items_per_page=items_per_page
        )
    
    return render_template("index.html", results=results, details=details, enh_list=enh_list, query=query, hotlist=hotlist, items_per_page=items_per_page)


@app.route("/api/hotlist")
def api_hotlist():
    """API endpoint to get all hotlist items as JSON without pagination"""
    item_db = get_item_db()
    try:
        all_hotlist = fetch_hotlist()
    except Exception:
        logger.exception("Failed to fetch hotlist for API")
        all_hotlist = []
    for item in all_hotlist:
        info = item_db.get(str(item["item_id"]), {})
        item["name"] = info.get("name", f"ID {item['item_id']}")
        item["image"] = info.get("image", "")
        # Provide enhancement label to avoid duplicating logic on the client
        try:
            item["enh_label"] = enh_name(item.get("enh_min", 0), item.get("enh_max", 0))
        except Exception:
            item["enh_label"] = ""
    all_hotlist.sort(key=lambda x: x["total_trades"], reverse=True)
    return jsonify({
        "items": all_hotlist,
        "items_per_page": app.config.get("ITEMS_PER_PAGE", 25)
    })


@app.route("/item/<item_id>")
def item_detail(item_id):
    item_db = get_item_db()
    item_info = item_db.get(item_id)
    if not item_info:
        return render_template("index.html", results="not_found", query="")
    market_data = fetch_market_data(item_id)
    if len(market_data) > 1:
        enh_list = [
            {
                "id": item_id,
                "name": item_info.get("name"),
                "image": item_info.get("image"),
                "enhancement_min": item["enhancement_min"],
                "enhancement_max": item["enhancement_max"]
            }
            for item in market_data
        ]
        return render_template("index.html", enh_list=enh_list, query=item_info.get("name", ""))
    else:
        details = {
            "id": item_id,
            "name": item_info.get("name"),
            "image": item_info.get("image"),
            "market_data": get_market_and_bidding(item_id)
        }
        return render_template("index.html", details=details, query=item_info.get("name", ""))

@app.route("/item/<item_id>/<int:enh_min>/<int:enh_max>")
def item_detail_enh(item_id, enh_min, enh_max):
    item_db = get_item_db()
    item_info = item_db.get(item_id)
    if not item_info:
        return render_template("index.html", results="not_found", query="")
    details = {
        "id": item_id,
        "name": item_info.get("name"),
        "image": item_info.get("image"),
        "market_data": get_market_and_bidding(item_id, enh_min, enh_max)
    }
    return render_template("index.html", details=details, query=item_info.get("name", ""))

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8520"))
    debug_env = os.getenv("FLASK_DEBUG", os.getenv("DEBUG", "0")).lower() in ("1", "true", "yes", "on")
    app.run(host=host, port=port, debug=debug_env)
