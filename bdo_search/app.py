import requests
import sys
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from bdo_huffman import unpack  


CACHE_FILE = os.path.expanduser("~/bdo_trading_post_arbitrage/bdo_search/item_cache_codex.json")
API_URL = "https://eu-trade.naeu.playblackdesert.com/Trademarket/GetWorldMarketSubList"
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

def load_item_db(cache_file):
    with open(cache_file, encoding="utf-8") as f:
        return json.load(f)

def unix_to_ro_time(ts):
    try:
        dt = datetime.fromtimestamp(ts, tz=ZoneInfo("Europe/Bucharest"))
        return dt.strftime("%d-%m-%Y %H:%M:%S")
    except Exception:
        return None

def find_item(query, item_db):
    query = query.lower()
    if query in item_db:
        return query, item_db[query]
    for k, v in item_db.items():
        if v.get("name", "").lower() == query:
            return k, v
    return None, None

def fetch_market_data(item_id):
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "BlackDesert"
    }
    payload = {
        "keyType": 0,
        "mainKey": int(item_id)
    }
    response = requests.post(API_URL, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()
    return parse_market_data(data.get("resultMsg", ""))

def fetch_bidding_info(item_id, sub_key):
    url = "https://eu-trade.naeu.playblackdesert.com/Trademarket/GetBiddingInfoList"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "BlackDesert"
    }
    payload = {
        "keyType": 0,
        "mainKey": int(item_id),
        "subKey": int(sub_key)
    }
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    # Dacă răspunsul este binar, decodifică-l
    try:
        decoded = unpack(response.content)
        return parse_bidding_info(decoded)
    except Exception as e:
        # Dacă nu e binar, încearcă să tratezi ca text
        try:
            decoded = response.json().get("resultMsg", "")
            return parse_bidding_info(decoded)
        except Exception:
            print(f"Error decoding bidding info: {e}")
            return None

def parse_bidding_info(decoded_str):
    """
    Primește un string de forma '60500000-0-5|62000000-0-1|66500000-0-1|...' și îl transformă în listă de dict-uri.
    """
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
            # Adaugă timpul uman în Romania
            item["last_sale_time_ro"] = unix_to_ro_time(item["last_sale_time"])
            items.append(item)
    return items


def main():
    if len(sys.argv) < 2:
        print("Usage: python app.py <item_id sau nume>")
        sys.exit(1)
    query = " ".join(sys.argv[1:]).strip()
    item_db = load_item_db(CACHE_FILE)
    item_id, item_info = find_item(query, item_db)
    if not item_id:
        print("Item not found!")
        sys.exit(1)
    market_data = fetch_market_data(item_id)
    # Pentru fiecare enhancement level, ia bidding info
    for item in market_data:
        sub_key = item["enhancement_max"]  # sau enhancement_min, depinde de ce vrei
        item["bidding_info"] = fetch_bidding_info(item_id, sub_key)
    output = {
        "id": item_id,
        "name": item_info.get("name"),
        "image": item_info.get("image"),
        "market_data": market_data
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
