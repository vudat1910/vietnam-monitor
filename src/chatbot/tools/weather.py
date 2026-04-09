import json
import os
import time
import requests
from langchain_core.tools import tool

_cache: dict = {}  
_CACHE_TTL = 600   

_LOCATION_FILE = os.path.join(os.path.dirname(__file__), "../../location.json")
try:
    with open(_LOCATION_FILE, encoding="utf-8") as f:
        _LOCATIONS = json.load(f)
except Exception:
    _LOCATIONS = {
        "Hà Nội": [105.8342, 21.0278], "Hồ Chí Minh": [106.6297, 10.8231],
        "Đà Nẵng": [108.2022, 16.0544], "Cần Thơ": [105.7469, 10.0452],
    }

_WMO_DESC = {
    0: "Trời quang", 1: "Ít mây", 2: "Có mây", 3: "Nhiều mây",
    45: "Sương mù", 48: "Sương mù đóng băng",
    51: "Mưa phùn nhẹ", 53: "Mưa phùn", 55: "Mưa phùn dày",
    61: "Mưa nhẹ", 63: "Mưa vừa", 65: "Mưa to",
    80: "Mưa rào nhẹ", 81: "Mưa rào", 82: "Mưa rào mạnh",
    95: "Có dông", 96: "Dông kèm mưa đá", 99: "Dông mưa đá lớn",
}

def _find_location(city: str):
    city_lower = city.lower().strip()
    for name, coords in _LOCATIONS.items():
        if city_lower == name.lower():
            return name, coords
    for name, coords in _LOCATIONS.items():
        if city_lower in name.lower() or name.lower() in city_lower:
            return name, coords
    return None, None


@tool
def get_weather(city: str, days: int = 3) -> str:
    """
    Lấy thời tiết hiện tại và dự báo N ngày tới cho tỉnh/thành phố Việt Nam.
    Dùng khi user hỏi về thời tiết, nhiệt độ, mưa, gió, dự báo.

    Args:
        city: tên tỉnh/thành phố (ví dụ: Hà Nội, Đà Nẵng, Hồ Chí Minh)
        days: số ngày dự báo TỪ NGÀY MAI (mặc định 3, tối đa 7).
              "3 ngày tới" → days=3, "5 ngày tới" → days=5, "tuần tới/7 ngày" → days=7.
              KHÔNG được truyền days+1, chỉ truyền đúng số ngày user yêu cầu.
    """
    name, coords = _find_location(city)
    if not coords:
        return f"Không tìm thấy '{city}'. Hãy nhập tên tỉnh/thành phố Việt Nam."

    days = max(1, min(int(days), 7))  

    cache_key = (name, days)
    if cache_key in _cache:
        ts, cached_result = _cache[cache_key]
        if time.time() - ts < _CACHE_TTL:
            return cached_result

    lon, lat = coords
    try:
        url = (
            f"http://localhost:5000/weather-proxy"
            f"?lat={lat}&lon={lon}&days={days + 1}"
        )
        resp = requests.get(url, timeout=10)
        if resp.status_code == 429:
            return "API thời tiết đang bận, vui lòng thử lại sau vài phút."
        data = resp.json()
        if "error" in data:
            return f"Lỗi thời tiết: {data['error']}"

        cur  = data["current"]
        desc = _WMO_DESC.get(cur["weathercode"], "Không rõ")

        lines = [
            f"🌤 Thời tiết {name} hiện tại:",
            f"  Nhiệt độ: {cur['temperature_2m']}°C | Độ ẩm: {cur['relative_humidity_2m']}% | Gió: {cur['windspeed_10m']} km/h",
            f"  Trạng thái: {desc}",
            "",
            f" Dự báo {days} ngày tới:",
        ]
        daily = data["daily"]
        for i in range(1, days + 1):
            if i >= len(daily["time"]):
                break
            rain = daily["precipitation_sum"][i] or 0
            lines.append(
                f"  {daily['time'][i]}: {_WMO_DESC.get(daily['weathercode'][i], '?')}, "
                f"{daily['temperature_2m_min'][i]}–{daily['temperature_2m_max'][i]}°C"
                + (f", mưa {rain}mm" if rain > 0 else "")
            )
        result = "\n".join(lines)
        _cache[cache_key] = (time.time(), result)  
        return result

    except Exception as e:
        return f"Lỗi lấy thời tiết {name}: {e}"
