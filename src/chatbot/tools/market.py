import time
import requests
from langchain_core.tools import tool

FLASK_BASE = "http://localhost:5000"

_INDEX_SYMBOLS = {"VNINDEX", "VN30", "HNX", "UPCOM"}

_cache: dict = {}   
_CACHE_TTL_INDEX = 60   
_CACHE_TTL_STOCK = 60   


def _get_cache(key: str, ttl: int):
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < ttl:
        return entry[1]
    return None


def _set_cache(key: str, value: str):
    _cache[key] = (time.time(), value)


@tool
def get_market(symbol: str = "") -> str:
    """
    Lấy dữ liệu thị trường chứng khoán Việt Nam.
    Dùng khi user hỏi về chứng khoán, chỉ số hoặc mã cổ phiếu cụ thể.

    Args:
        symbol: mã chứng khoán hoặc chỉ số.
                Chỉ số thị trường: VNINDEX, VN30, HNX, UPCOM
                Mã cổ phiếu: VNM, HPG, VIC, VCB, FPT, ... (để trống nếu hỏi chung)
    """
    symbol_upper = symbol.strip().upper()

    if not symbol_upper or symbol_upper in _INDEX_SYMBOLS:
        cache_key = f"index:{symbol_upper or 'all'}"
        cached = _get_cache(cache_key, _CACHE_TTL_INDEX)
        if cached:
            return cached

        try:
            resp = requests.get(f"{FLASK_BASE}/market", timeout=5)
            resp.raise_for_status()
            data = resp.json()

            indices = data.get("indices", {})
            updated = data.get("updatedAt", "không rõ")

            if not indices:
                return "Hiện không có dữ liệu thị trường."

            lines = [f"Thị trường chứng khoán (cập nhật: {updated})\n"]
            for name, info in indices.items():
                if symbol_upper and name != symbol_upper:
                    continue
                if not info:
                    lines.append(f"  {name}: không có dữ liệu")
                    continue
                price  = info.get("price", "?")
                change = info.get("change", 0)
                pct    = info.get("change_pct", 0)
                arrow  = "▲" if (change or 0) >= 0 else "▼"
                sign   = "+" if (change or 0) >= 0 else ""
                lines.append(f"  {name}: {price:,.2f} {arrow} {sign}{change} ({sign}{pct}%)")

            result = "\n".join(lines)
            _set_cache(cache_key, result)
            return result
        except Exception as e:
            return f"Lỗi lấy dữ liệu thị trường: {str(e)}"

    cache_key = f"stock:{symbol_upper}"
    cached = _get_cache(cache_key, _CACHE_TTL_STOCK)
    if cached:
        return cached

    try:
        from vnstock import stock_historical_data
        import datetime

        end   = datetime.date.today().isoformat()
        start = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()

        df = stock_historical_data(symbol_upper, start, end, "1D", type="stock")
        if df is None or len(df) == 0:
            return f"Không tìm thấy dữ liệu cho mã '{symbol_upper}'. Kiểm tra lại mã cổ phiếu."

        latest = df.iloc[-1]
        prev   = df.iloc[-2] if len(df) > 1 else None

        close  = float(latest.get("close", 0))
        open_  = float(latest.get("open", close))
        high   = float(latest.get("high", close))
        low    = float(latest.get("low", close))
        vol    = int(latest.get("volume", 0))
        date   = str(latest.get("time", ""))[:10]

        change     = close - float(prev["close"]) if prev is not None else 0
        change_pct = (change / float(prev["close"]) * 100) if prev is not None and float(prev["close"]) > 0 else 0
        arrow      = "▲" if change >= 0 else "▼"
        sign       = "+" if change >= 0 else ""

        result = (
            f"📈 Cổ phiếu {symbol_upper} ({date})\n"
            f"  Giá đóng cửa: {close:,.0f} {arrow} {sign}{change:,.0f} ({sign}{change_pct:.2f}%)\n"
            f"  Mở cửa: {open_:,.0f} | Cao: {high:,.0f} | Thấp: {low:,.0f}\n"
            f"  Khối lượng: {vol:,} cổ phiếu"
        )
        _set_cache(cache_key, result)
        return result

    except ImportError:
        return f"Không thể tra cứu mã '{symbol_upper}' — thư viện vnstock chưa cài."
    except Exception as e:
        return f"Lỗi tra cứu mã '{symbol_upper}': {str(e)}"
