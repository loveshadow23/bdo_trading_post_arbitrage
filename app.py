#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Black Desert Online Trading Post Arbitrage Application
A Flask web application to help find profitable items on the BDO marketplace.
"""

import requests
import json
import os
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, request, jsonify
from huffman_binary_decode import unpack

# =============================================================================
# Configuration
# =============================================================================
CONFIG = {
    "CACHE_FILE": os.path.expanduser("~/bdo_trading_post_arbitrage/item_cache_garmoth.json"),
    "API_BASE_URL": "https://eu-trade.naeu.playblackdesert.com",
    "DEFAULT_TIMEZONE": "Europe/Bucharest",
    "ITEMS_PER_PAGE": 25,
    "LOG_FILE": "bdo_market_search.log",
    "LOG_LEVEL": logging.INFO,
    "DEFAULT_HEADERS": {
        "Content-Type": "application/json", 
        "User-Agent": "BlackDesert"
    },
    "API_ENDPOINTS": {
        "MARKET_SUBLIST": "/Trademarket/GetWorldMarketSubList",
        "BIDDING_INFO": "/Trademarket/GetBiddingInfoList",
        "HOTLIST": "/Trademarket/GetWorldMarketHotList"
    },
    "MARKET_FIELDS": [
        "item_id", "enhancement_min", "enhancement_max", "base_price", "current_stock",
        "total_trades", "price_hardcap_min", "price_hardcap_max", "last_sale_price", "last_sale_time"
    ],
    "ENHANCEMENT_LABELS": ["", "PRI (I)", "DUO (II)", "TRI (III)", "TET (IV)", "PEN (V)"]
}

# Initialize Flask app
app = Flask(__name__)
app.config["ITEMS_PER_PAGE"] = CONFIG["ITEMS_PER_PAGE"]

# Process-level cache for item database
_item_db_cache = None

# =============================================================================
# Logging Configuration
# =============================================================================
def setup_logging():
    """Configure application logging with rotation and stdout output"""
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # File handler with rotation
    file_handler = RotatingFileHandler(
        CONFIG["LOG_FILE"], 
        maxBytes=1024 * 1024 * 5,  # 5MB
        backupCount=3
    )
    file_handler.setFormatter(log_formatter)
    
    # Console (stdout) handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    
    # Configure logger
    logger = logging.getLogger('bdo_market')
    logger.setLevel(CONFIG["LOG_LEVEL"])
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# Initialize logger
logger = setup_logging()

# =============================================================================
# Utility Functions
# =============================================================================
def get_item_db():
    """
    Load and cache the item database.
    
    Returns:
        dict: The item database mapping IDs to item info
    """
    global _item_db_cache
    if _item_db_cache is None:
        logger.info(f"Loading item database from {CONFIG['CACHE_FILE']}")
        try:
            with open(CONFIG["CACHE_FILE"], encoding="utf-8") as f:
                _item_db_cache = json.load(f)
            logger.info(f"Successfully loaded {len(_item_db_cache)} items")
        except Exception as e:
            logger.error(f"Failed to load item database: {str(e)}")
            _item_db_cache = {}
    return _item_db_cache

def unix_to_local_time(timestamp):
    """
    Convert a Unix timestamp to formatted local time.
    
    Args:
        timestamp (int): Unix timestamp
        
    Returns:
        str: Formatted date/time string or "-" if conversion fails
    """
    try:
        return datetime.fromtimestamp(
            timestamp, 
            tz=ZoneInfo(CONFIG["DEFAULT_TIMEZONE"])
        ).strftime("%d.%m.%Y %H:%M")
    except Exception as e:
        logger.warning(f"Time conversion error: {str(e)}")
        return "-"

def find_items(query, item_db):
    """
    Find items in the database by ID or name.
    
    Args:
        query (str): Search query
        item_db (dict): Item database
        
    Returns:
        list: List of tuples (item_id, item_info) that match the query
    """
    query = query.lower()
    results = []
    
    # Search by exact ID
    if query in item_db:
        results.append((query, item_db[query]))
    
    # Search by exact or partial name
    for item_id, item_info in item_db.items():
        name = item_info.get("name", "").lower()
        if name == query or query in name:
            if (item_id, item_info) not in results:
                results.append((item_id, item_info))
    
    logger.info(f"Search for '{query}' found {len(results)} results")
    return results

# =============================================================================
# API Interaction
# =============================================================================
def api_request(endpoint, payload=None, method="POST"):
    """
    Make a request to the BDO API.
    
    Args:
        endpoint (str): API endpoint path
        payload (dict, optional): Request payload
        method (str, optional): HTTP method, defaults to POST
        
    Returns:
        dict or str: API response
        
    Raises:
        requests.RequestException: If the API request fails
    """
    url = f"{CONFIG['API_BASE_URL']}{endpoint}"
    headers = CONFIG["DEFAULT_HEADERS"]
    
    start_time = time.time()
    logger.debug(f"API request to {endpoint} with payload: {payload}")
    
    try:
        if method.upper() == "POST":
            if payload is None:
                response = requests.post(url, headers=headers, data="")
            else:
                response = requests.post(url, headers=headers, json=payload)
        else:
            response = requests.get(url, headers=headers, params=payload)
            
        response.raise_for_status()
        duration = time.time() - start_time
        logger.debug(f"API request completed in {duration:.2f}s")
        
        return response
    except requests.RequestException as e:
        logger.error(f"API request failed: {str(e)}")
        raise

def fetch_market_data(item_id):
    """
    Fetch market data for an item.
    
    Args:
        item_id (str): Item ID
        
    Returns:
        list: List of market data entries
    """
    logger.info(f"Fetching market data for item ID: {item_id}")
    try:
        payload = {"keyType": 0, "mainKey": int(item_id)}
        response = api_request(
            CONFIG["API_ENDPOINTS"]["MARKET_SUBLIST"], 
            payload
        )
        
        return parse_market_data(response.json().get("resultMsg", ""))
    except Exception as e:
        logger.error(f"Error fetching market data: {str(e)}")
        return []

def fetch_bidding_info(item_id, sub_key):
    """
    Fetch bidding information for an item.
    
    Args:
        item_id (str): Item ID
        sub_key (int): Enhancement level key
        
    Returns:
        list: List of bidding data entries
    """
    logger.info(f"Fetching bidding info for item ID: {item_id}, sub_key: {sub_key}")
    try:
        payload = {"keyType": 0, "mainKey": int(item_id), "subKey": int(sub_key)}
        response = api_request(
            CONFIG["API_ENDPOINTS"]["BIDDING_INFO"], 
            payload
        )
        
        try:
            decoded = unpack(response.content)
            return parse_bidding_info(decoded)
        except Exception as decode_err:
            logger.warning(f"Failed to decode binary response: {str(decode_err)}, trying JSON fallback")
            try:
                return parse_bidding_info(response.json().get("resultMsg", ""))
            except Exception as json_err:
                logger.error(f"Failed JSON fallback: {str(json_err)}")
                return []
    except Exception as e:
        logger.error(f"Error fetching bidding info: {str(e)}")
        return []

def fetch_hotlist():
    """
    Fetch and parse the current hot items list.
    
    Returns:
        list: List of hot items with market data
    """
    logger.info("Fetching hot items list")
    try:
        response = api_request(CONFIG["API_ENDPOINTS"]["HOTLIST"])
        decoded = unpack(response.content)
        
        if isinstance(decoded, bytes):
            decoded = decoded.decode('utf-8')
            
        items = []
        for entry in decoded.strip("|").split("|"):
            fields = entry.split("-")
            if len(fields) == 12:
                item_id = fields[0]
                sale_time = int(fields[11])
                items.append({
                    "item_id": item_id,
                    "enh_min": int(fields[1]),
                    "enh_max": int(fields[2]),
                    "base_price": int(fields[3]),
                    "stock": int(fields[4]),
                    "total_trades": int(fields[5]),
                    "price_dir": int(fields[6]),   # 1 = down, 2 = up
                    "price_change": int(fields[7]),
                    "price_min": int(fields[8]),
                    "price_max": int(fields[9]),
                    "last_sale_price": int(fields[10]),
                    "last_sale_time": sale_time,
                    "last_sale_time_ro": unix_to_local_time(sale_time),
                })
        
        logger.info(f"Fetched {len(items)} hot items")
        return items
    except Exception as e:
        logger.error(f"Error fetching hot items: {str(e)}")
        return []

# =============================================================================
# Data Parsing
# =============================================================================
def parse_bidding_info(decoded_str):
    """
    Parse bidding information from API response.
    
    Args:
        decoded_str (str): Decoded API response
        
    Returns:
        list: List of parsed bidding information
    """
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
    """
    Parse market data from API response.
    
    Args:
        result_msg (str): API response message
        
    Returns:
        list: List of parsed market data entries
    """
    if not result_msg:
        return []
        
    items = []
    for entry in result_msg.strip("|").split("|"):
        values = entry.split("-")
        if len(values) == 10:
            item = {CONFIG["MARKET_FIELDS"][i]: int(values[i]) for i in range(10)}
            item["last_sale_time_ro"] = unix_to_local_time(item["last_sale_time"])
            items.append(item)
    return items

def get_market_and_bidding(item_id, enh_min=None, enh_max=None):
    """
    Get combined market and bidding data for an item.
    
    Args:
        item_id (str): Item ID
        enh_min (int, optional): Minimum enhancement level
        enh_max (int, optional): Maximum enhancement level
        
    Returns:
        list: Combined market and bidding data
    """
    market_data = fetch_market_data(item_id)
    
    # Filter by enhancement level if specified
    if enh_min is not None and enh_max is not None:
        market_data = [
            item for item in market_data 
            if item["enhancement_min"] == enh_min and item["enhancement_max"] == enh_max
        ]
    
    # Add bidding info to each market data entry
    for item in market_data:
        sub_key = item["enhancement_max"]
        item["bidding_info"] = fetch_bidding_info(item_id, sub_key)
        if item["bidding_info"]:
            item["bidding_info"].sort(key=lambda x: x["price"], reverse=True)
    
    return market_data

# =============================================================================
# Template Filters
# =============================================================================
@app.template_filter('format_number')
def format_number_filter(value):
    """
    Format a number with thousands separators.
    
    Args:
        value: Number to format
        
    Returns:
        str: Formatted number
    """
    try:
        return "{:,}".format(int(value))
    except Exception:
        return value

@app.template_filter('enh_name')
def enh_name(min_e, max_e, item_id=None):
    """
    Get the display name for an enhancement level.
    
    Args:
        min_e (int): Minimum enhancement level
        max_e (int): Maximum enhancement level
        item_id (str, optional): Item ID
        
    Returns:
        str: Enhancement level display name
    """
    # Determine if this is an accessory (only uses PRI-PEN system)
    # Accessories typically have enhancement levels from 0-5 or 1-5
    is_accessory = max_e <= 5 
    
    if min_e == max_e:
        if min_e == 0:
            return ""
            
        # For accessories that only use PRI-PEN system, map directly
        if is_accessory and 1 <= min_e <= 5:
            return CONFIG["ENHANCEMENT_LABELS"][min_e]
        
        # For standard items that use +1 to +15 system
        if 1 <= min_e <= 15:
            return f"+{min_e}"
            
        # For standard items that continue to PRI-PEN after +15
        if 16 <= min_e <= 20:
            return CONFIG["ENHANCEMENT_LABELS"][min_e - 15]
    
    return f"{min_e} to {max_e}"

# =============================================================================
# Route Handlers
# =============================================================================
@app.route("/", methods=["GET", "POST"])
def index():
    """
    Handle requests to the main page.
    """
    results = details = enh_list = None
    query = ""
    hotlist = None
    page = request.args.get('page', 1, type=int)
    items_per_page = app.config["ITEMS_PER_PAGE"]
    
    # Handle search form submission
    if request.method == "POST":
        query = request.form.get("query", "").strip()
        if query:
            logger.info(f"Search request: '{query}'")
            item_db = get_item_db()
            matches = find_items(query, item_db)
            
            if matches:
                # Single exact match - show details or enhancement options
                if len(matches) == 1:
                    item_id, item_info = matches[0]
                    market_data = fetch_market_data(item_id)
                    
                    # Multiple enhancement levels available
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
                    # Single enhancement level
                    else:
                        details = {
                            "id": item_id,
                            "name": item_info.get("name"),
                            "image": item_info.get("image"),
                            "market_data": get_market_and_bidding(item_id)
                        }
                # Multiple matches - show search results
                else:
                    results = [
                        {
                            "id": item_id,
                            "name": item_info.get("name"),
                            "image": item_info.get("image")
                        }
                        for item_id, item_info in matches
                    ]
            # No matches found
            else:
                results = "not_found"
                logger.info(f"No items found for query: '{query}'")
    
    # Show hotlist on landing page when no search is active
    if not query and not results and not details and not enh_list:
        logger.debug("Loading hotlist for landing page")
        item_db = get_item_db()
        all_hotlist = fetch_hotlist()
        
        # Add item details from database
        for item in all_hotlist:
            info = item_db.get(str(item["item_id"]), {})
            item["name"] = info.get("name", f"ID {item['item_id']}")
            item["image"] = info.get("image", "")
        
        # Sort by total trades
        all_hotlist.sort(key=lambda x: x["total_trades"], reverse=True)
        
        # Calculate pagination
        total_items = len(all_hotlist)
        total_pages = (total_items + items_per_page - 1) // items_per_page
        page = min(max(page, 1), total_pages)  # Ensure page is within valid range
        
        # Get items for current page
        start_idx = (page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, total_items)
        hotlist = all_hotlist[start_idx:end_idx]
        
        logger.debug(f"Displaying hotlist page {page}/{total_pages} ({len(hotlist)} items)")
        
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
    
    return render_template(
        "index.html", 
        results=results, 
        details=details, 
        enh_list=enh_list, 
        query=query, 
        hotlist=hotlist, 
        items_per_page=items_per_page
    )

@app.route("/api/hotlist")
def api_hotlist():
    """
    API endpoint to get all hotlist items as JSON without pagination.
    
    Returns:
        Response: JSON response with hotlist items
    """
    logger.info("API request for hotlist data")
    item_db = get_item_db()
    all_hotlist = fetch_hotlist()
    
    for item in all_hotlist:
        info = item_db.get(str(item["item_id"]), {})
        item["name"] = info.get("name", f"ID {item['item_id']}")
        item["image"] = info.get("image", "")
    
    all_hotlist.sort(key=lambda x: x["total_trades"], reverse=True)
    
    return jsonify({
        "items": all_hotlist,
        "items_per_page": app.config.get("ITEMS_PER_PAGE", 25)
    })

@app.route("/item/<item_id>")
def item_detail(item_id):
    """
    Display item details page.
    
    Args:
        item_id (str): Item ID
        
    Returns:
        Response: Rendered template with item details
    """
    logger.info(f"Item detail request for ID: {item_id}")
    item_db = get_item_db()
    item_info = item_db.get(item_id)
    
    if not item_info:
        logger.warning(f"Item not found: {item_id}")
        return render_template("index.html", results="not_found", query="")
    
    market_data = fetch_market_data(item_id)
    
    # Multiple enhancement levels available
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
    # Single enhancement level
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
    """
    Display item details for a specific enhancement level.
    
    Args:
        item_id (str): Item ID
        enh_min (int): Minimum enhancement level
        enh_max (int): Maximum enhancement level
        
    Returns:
        Response: Rendered template with item details
    """
    logger.info(f"Item detail request for ID: {item_id}, enhancement: {enh_min}-{enh_max}")
    item_db = get_item_db()
    item_info = item_db.get(item_id)
    
    if not item_info:
        logger.warning(f"Item not found: {item_id}")
        return render_template("index.html", results="not_found", query="")
    
    details = {
        "id": item_id,
        "name": item_info.get("name"),
        "image": item_info.get("image"),
        "market_data": get_market_and_bidding(item_id, enh_min, enh_max)
    }
    
    return render_template("index.html", details=details, query=item_info.get("name", ""))

# =============================================================================
# Main Entry Point
# =============================================================================
if __name__ == "__main__":
    logger.info("Starting BDO Trading Post Arbitrage application")
    app.run(host="0.0.0.0", port=8520, debug=True)
