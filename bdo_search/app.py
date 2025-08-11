import sys
import json

def load_items(filename="item_cache_codex.json"):
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)

def find_item(items, query):
    # Caută după ID direct
    if query in items:
        return {query: items[query]}
    # Caută după nume (case-insensitive)
    query_lower = query.lower()
    for item_id, data in items.items():
        if data.get("name", "").lower() == query_lower:
            return {item_id: data}
    return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python app.py <item_id sau nume>")
        sys.exit(1)
    
    query = sys.argv[1]
    items = load_items()
    result = find_item(items, query)
    
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Item not found.")

if __name__ == "__main__":
    main()
