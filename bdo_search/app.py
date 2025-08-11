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
    "item_id", "enhancement_min", "enhancement_max", "base_price", "current_stock",
    "total_trades", "price_hardcap_min", "price_hardcap_max", "last_sale_price", "last_sale_time"
]

app = Flask(__name__)

# Cache la nivel de proces pentru baza de date iteme
_item_db_cache = None
def get_item_db():
    global _item_db_cache
    if _item_db_cache is None:
        with open(CACHE_FILE, encoding="utf-8") as f:
            _item_db_cache = json.load(f)
    return _item_db_cache

@app.template_filter('format_number')
def format_number_filter(value):
    try:
        return "{:,}".format(int(value))
    except Exception:
        return value

@app.template_filter('enh_name')
def enh_name(min_e, max_e, _):
    if min_e == max_e:
        if min_e == 0:
            return ""
        if 1 <= min_e <= 15:
            return f"+{min_e}"
        acc_labels = ["", "PRI (I)", "DUO (II)", "TRI (III)", "TET (IV)", "PEN (V)"]
        if 16 <= min_e <= 20:
            return acc_labels[min_e - 15]
    return f"{min_e} to {max_e}"

def unix_to_ro_time(ts):
    try:
        return datetime.fromtimestamp(ts, tz=ZoneInfo("Europe/Bucharest")).strftime("%d-%m-%Y %H:%M:%S")
    except Exception:
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
    headers = {"Content-Type": "application/json", "User-Agent": "BlackDesert"}
    payload = {"keyType": 0, "mainKey": int(item_id)}
    r = requests.post(f"{API_BASE_URL}/Trademarket/GetWorldMarketSubList", headers=headers, json=payload)
    r.raise_for_status()
    return parse_market_data(r.json().get("resultMsg", ""))

def fetch_bidding_info(item_id, sub_key):
    headers = {"Content-Type": "application/json", "User-Agent": "BlackDesert"}
    payload = {"keyType": 0, "mainKey": int(item_id), "subKey": int(sub_key)}
    r = requests.post(f"{API_BASE_URL}/Trademarket/GetBiddingInfoList", headers=headers, json=payload)
    r.raise_for_status()
    try:
        decoded = unpack(r.content)
        return parse_bidding_info(decoded)
    except Exception:
        try:
            return parse_bidding_info(r.json().get("resultMsg", ""))
        except Exception:
            return []

def parse_bidding_info(decoded_str):
    if not decoded_str:
        return []
    result = []
    for entry in decoded_str.strip("|").split("|"):
        values = entry.split("-")
        if len(values) == 3:
            result.append({
                "price": int(values[0]),
                "sell_orders": int(values[1]),
                "buy_orders": int(values[2])
            })
    return result

def parse_market_data(result_msg):
    if not result_msg:
        return []
    items = []
    for entry in result_msg.strip("|").split("|"):
        values = entry.split("-")
        if len(values) == 10:
            item = {FIELDS[i]: int(values[i]) for i in range(10)}
            item["last_sale_time_ro"] = unix_to_ro_time(item["last_sale_time"])
            items.append(item)
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
    return render_template("index.html", results=results, details=details, enh_list=enh_list, query=query)

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
    app.run(host="0.0.0.0", port=8520, debug=True)
