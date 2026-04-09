import time
import requests
from langchain_core.tools import tool

FLASK_BASE = "http://localhost:5000"

_cache: dict = {}
_CACHE_TTL_GOLD = 300   
_CACHE_TTL_FUEL = 300   


def _get_cache(key: str, ttl: int):
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < ttl:
        return entry[1]
    return None


def _set_cache(key: str, value: str):
    _cache[key] = (time.time(), value)


@tool
def get_commodity(item: str = "all") -> str:
    """
    Lấy giá vàng và xăng dầu hiện tại.
    Dùng khi user hỏi về giá vàng (SJC, DOJI) hoặc giá xăng dầu.
    Tham số item: 'gold' (vàng), 'fuel' (xăng dầu), 'all' (tất cả).
    """
    result = []

    if item in ("gold", "all"):
        cached = _get_cache("gold", _CACHE_TTL_GOLD)
        if cached:
            result.append(cached)
        else:
            try:
                resp = requests.get(f"{FLASK_BASE}/commodity/gold/current", timeout=20)
                resp.raise_for_status()
                data = resp.json()
                sources = data.get("sources", {})
                updated = data.get("updatedAt", "không rõ")

                lines = [f"🥇 Giá vàng (cập nhật: {updated})"]
                for source_name, items in sources.items():
                    lines.append(f"\n  {source_name}:")
                    if isinstance(items, list):
                        for item_data in items[:3]:
                            name = item_data.get("name", "")
                            buy  = item_data.get("buy", "?")
                            sell = item_data.get("sell", "?")
                            lines.append(f"    {name}: Mua {buy} | Bán {sell}")
                    elif isinstance(items, dict):
                        buy  = items.get("buy", "?")
                        sell = items.get("sell", "?")
                        lines.append(f"    Mua {buy} | Bán {sell}")

                gold_str = "\n".join(lines)
                _set_cache("gold", gold_str)
                result.append(gold_str)
            except Exception as e:
                result.append(f"Lỗi lấy giá vàng: {str(e)}")

    if item in ("fuel", "all"):
        cached = _get_cache("fuel", _CACHE_TTL_FUEL)
        if cached:
            result.append(cached)
        else:
            try:
                resp = requests.get(f"{FLASK_BASE}/commodity/fuel/current", timeout=20)
                resp.raise_for_status()
                data = resp.json()

                lines = ["⛽ Giá xăng dầu hiện tại:"]
                if isinstance(data, list):
                    for fuel in data:
                        name  = fuel.get("name", fuel.get("type", "?"))
                        price = fuel.get("price", "?")
                        lines.append(f"  {name}: {price}")
                elif isinstance(data, dict):
                    updated = data.get("updatedAt", "")
                    if updated:
                        lines[0] += f" (cập nhật: {updated})"
                    for k, v in data.items():
                        if k != "updatedAt":
                            lines.append(f"  {k}: {v}")

                fuel_str = "\n".join(lines)
                _set_cache("fuel", fuel_str)
                result.append(fuel_str)
            except Exception as e:
                result.append(f"Lỗi lấy giá xăng dầu: {str(e)}")

    return "\n\n".join(result) if result else "Không có dữ liệu."
