import requests
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request
from bdo_huffman import unpack

CACHE_FILE = os.path.expanduser("~/bdo_trading_post_arbitrage/bdo_search/item_cache_garmoth.json")
API_BASE_URL = "https://eu-trade.naeu.playblackdesert.com"
FIELDS = [
    "item_id",
    "enhancement_min",
    "enhancement_max",
    "base_price",
    "current_stock",
    "total_trades",
    "price_hardcap_min",
    "price_hardcap_max",
    "last_sale_price",
    "last_sale_time"
]

app = Flask(__name__)

@app.template_filter('format_number')
def format_number_filter(value):
    """Format numbers with thousands separator (comma)."""
    try:
        return "{:,}".format(int(value))
    except (ValueError, TypeError):
        return value
        
def load_item_db(cache_file):
    with open(cache_file, encoding="utf-8") as f:
        return json.load(f)

def unix_to_ro_time(ts):
    try:
        dt = datetime.fromtimestamp(ts, tz=ZoneInfo("Europe/Bucharest"))
        return dt.strftime("%d-%m-%Y %H:%M:%S")
    except Exception:
        return None

@app.template_filter('enh_name')
def enh_name(min_e, max_e, sid):
    """Format enhancement name in a more user-friendly way."""
    # Pentru Base (0), nu afișăm nimic
    if min_e == 0 and max_e == 0:
        return ""
    
    # Pentru enhancement-uri de la +1 la +15
    if min_e == max_e and 1 <= min_e <= 15:
        return f"+{min_e}"
    
    # Pentru enhancement-uri PRI, DUO, TRI, TET, PEN
    acc_labels = ["", "PRI (I)", "DUO (II)", "TRI (III)", "TET (IV)", "PEN (V)"]
    if min_e == max_e and 16 <= min_e <= 20:
        idx = min_e - 15
        if 1 <= idx <= 5:
            return acc_labels[idx]
    
    # Pentru alte cazuri (range-uri)
    return f"{min_e} to {max_e}"

def find_items(query, item_db):
    query = query.lower()
    results = []
    # Caută după id exact
    if query in item_db:
        results.append((query, item_db[query]))
    # Caută după nume exact
    for k, v in item_db.items():
        if v.get("name", "").lower() == query and (k, v) not in results:
            results.append((k, v))
    # Caută după potrivire parțială în nume
    for k, v in item_db.items():
        if query in v.get("name", "").lower() and (k, v) not in results:
            results.append((k, v))
    return results

def fetch_market_data(item_id):
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "BlackDesert"
    }
    payload = {
        "keyType": 0,
        "mainKey": int(item_id)
    }
    response = requests.post(f"{API_BASE_URL}/Trademarket/GetWorldMarketSubList", headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()
    return parse_market_data(data.get("resultMsg", ""))

def fetch_bidding_info(item_id, sub_key):
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "BlackDesert"
    }
    payload = {
        "keyType": 0,
        "mainKey": int(item_id),
        "subKey": int(sub_key)
    }
    response = requests.post(f"{API_BASE_URL}/Trademarket/GetBiddingInfoList", headers=headers, json=payload)
    response.raise_for_status()
    try:
        decoded = unpack(response.content)
        return parse_bidding_info(decoded)
    except Exception as e:
        try:
            decoded = response.json().get("resultMsg", "")
            return parse_bidding_info(decoded)
        except Exception:
            print(f"Error decoding bidding info: {e}")
            return None

def parse_bidding_info(decoded_str):
    result = []
    if not decoded_str:
        return result
    entries = decoded_str.strip("|").split("|")
    for entry in entries:
        values = entry.split("-")
        if len(values) == 3:
            result.append({
                "price": int(values[0]),
                "sell_orders": int(values[1]),
                "buy_orders": int(values[2])
            })
    return result

def parse_market_data(result_msg):
    items = []
    if not result_msg:
        return items
    entries = result_msg.strip("|").split("|")
    for entry in entries:
        values = entry.split("-")
        if len(values) == 10:
            item = {FIELDS[i]: int(values[i]) for i in range(10)}
            item["last_sale_time_ro"] = unix_to_ro_time(item["last_sale_time"])
            items.append(item)
    return items

@app.route("/", methods=["GET", "POST"])
def index():
    results = None
    details = None
    query = ""
    if request.method == "POST":
        query = request.form.get("query", "").strip()
        if query:
            item_db = load_item_db(CACHE_FILE)
            matches = find_items(query, item_db)
            if matches:
                # Dacă e doar unul, arată direct detaliile
                if len(matches) == 1:
                    item_id, item_info = matches[0]
                    market_data = fetch_market_data(item_id)
                    for item in market_data:
                        sub_key = item["enhancement_max"]
                        item["bidding_info"] = fetch_bidding_info(item_id, sub_key)
                    details = {
                        "id": item_id,
                        "name": item_info.get("name"),
                        "image": item_info.get("image"),
                        "market_data": market_data
                    }
                else:
                    # Returnează lista de rezultate pentru alegere
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
    return render_template("index.html", results=results, details=details, query=query)

@app.route("/item/<item_id>")
def item_detail(item_id):
    item_db = load_item_db(CACHE_FILE)
    item_info = item_db.get(item_id)
    if not item_info:
        return render_template("index.html", results="not_found", query="")
    market_data = fetch_market_data(item_id)
    for item in market_data:
        sub_key = item["enhancement_max"]
        item["bidding_info"] = fetch_bidding_info(item_id, sub_key)
        if item["bidding_info"]:
            item["bidding_info"].sort(key=lambda x: x["price"], reverse=True)
    details = {
        "id": item_id,
        "name": item_info.get("name"),
        "image": item_info.get("image"),
        "market_data": market_data
    }
    return render_template("index.html", details=details, query=item_info.get("name", ""))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8520, debug=True)
