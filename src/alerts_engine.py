import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import requests

SEVERITY_ORDER = {"critical": 4, "warning": 3, "watch": 2, "info": 1, "ok": 0}

def _wmo_label_vi(code: int) -> str:
    c = int(code)
    fine = {
        0: "Trời quang",
        1: "Chủ yếu quang",
        2: "Có mây một phần",
        3: "Nhiều mây",
        45: "Sương mù",
        48: "Sương mù đóng băng",
        51: "Mưa phùn nhẹ",
        53: "Mưa phùn vừa",
        55: "Mưa phùn dày",
        61: "Mưa nhỏ",
        63: "Mưa vừa",
        65: "Mưa to",
        71: "Tuyết nhỏ",
        73: "Tuyết vừa",
        75: "Tuyết dày",
        77: "Hạt băng",
        80: "Mưa rào nhẹ",
        81: "Mưa rào vừa",
        82: "Mưa rào mạnh",
        85: "Tuyết rào nhẹ",
        86: "Tuyết rào mạnh",
        95: "Dông / sét",
        96: "Dông có mưa đá",
        99: "Dông mạnh, mưa đá",
    }
    if c in fine:
        return fine[c]
    if c in (51, 53, 55, 61, 63, 65, 80, 81, 82):
        return "Mưa"
    if c in (71, 73, 75, 85, 86):
        return "Tuyết"
    if c in (95, 96, 99):
        return "Giông bão"
    if c in (45, 48):
        return "Sương mù"
    return "Không rõ"

RISK_KEYWORDS = (
    "lũ lụt",
    "lũ quét",
    "lũ ",
    "bão số",
    "bão ",
    "áp thấp",
    "sạt lở",
    "ngập úng",
    "ngập sâu",
    "mưa lớn",
    "mưa đá",
    "giông",
    "sét ",
    "thiên tai",
    "hạn hán",
    "cháy rừng",
    "động đất",
    "sóng thần",
)


def _norm(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


def load_locations(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for name, coords in raw.items():
        if name == "Việt Nam":
            continue
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            continue
        out[name] = [float(coords[0]), float(coords[1])]
    return out


def _fetch_daily(lat, lon):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&daily=weathercode,temperature_2m_max,temperature_2m_min,"
        "precipitation_sum,precipitation_probability_max"
        "&forecast_days=4&timezone=Asia%2FBangkok"
    )
    r = requests.get(url, timeout=18)
    r.raise_for_status()
    return r.json().get("daily") or {}


def _weather_daily_snapshot(daily):
    """Tóm tắt 4 ngày cho popup bản đồ (luôn gửi kèm GeoJSON)."""
    if not daily:
        return []
    codes = daily.get("weathercode") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    precip = daily.get("precipitation_sum") or []
    prob = daily.get("precipitation_probability_max") or []
    times = daily.get("time") or []
    n = min(4, len(codes), len(times) or 999)
    out = []
    for i in range(n):
        wc = int(codes[i]) if i < len(codes) else 0
        row = {
            "date": times[i] if i < len(times) else "",
            "label": _wmo_label_vi(wc),
            "tmax": float(tmax[i]) if i < len(tmax) and tmax[i] is not None else None,
            "tmin": float(tmin[i]) if i < len(tmin) and tmin[i] is not None else None,
            "precip_mm": float(precip[i]) if i < len(precip) and precip[i] is not None else None,
            "prob_pct": int(prob[i]) if i < len(prob) and prob[i] is not None else None,
        }
        out.append(row)
    return out


def _weather_alerts_for_province(daily):
    """Sinh danh sách alert dict từ block daily Open-Meteo."""
    alerts = []
    if not daily:
        return alerts

    codes = daily.get("weathercode") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    precip = daily.get("precipitation_sum") or []
    prob = daily.get("precipitation_probability_max") or []
    times = daily.get("time") or []

    n = min(len(codes), 4, max(len(tmax), len(precip), 1))

    for i in range(n):
        day_label = times[i] if i < len(times) else f"+{i}d"
        wc = int(codes[i]) if i < len(codes) else 0
        wlabel = _wmo_label_vi(wc)
        mx = float(tmax[i]) if i < len(tmax) else None
        mn = float(tmin[i]) if i < len(tmin) else None
        pr = float(precip[i]) if i < len(precip) else 0.0
        pb = int(prob[i]) if i < len(prob) else 0
        temp_bits = []
        if mx is not None:
            temp_bits.append(f"cao ~{mx:.0f}°C")
        if mn is not None:
            temp_bits.append(f"thấp ~{mn:.0f}°C")
        temp_line = ", ".join(temp_bits) if temp_bits else ""

        # Giông bão (WMO)
        if wc in (95, 96, 99):
            alerts.append(
                {
                    "layer": "weather",
                    "severity": "critical",
                    "title": "Giông bão / sét",
                    "summary": f"{day_label}: {wlabel}. {temp_line}".strip(),
                }
            )
        elif wc in (82, 81, 65, 63):
            alerts.append(
                {
                    "layer": "weather",
                    "severity": "warning",
                    "title": "Mưa lớn",
                    "summary": f"{day_label}: {wlabel}" + (f", {temp_line}" if temp_line else ""),
                }
            )
        elif pr >= 80:
            alerts.append(
                {
                    "layer": "weather",
                    "severity": "warning",
                    "title": "Lượng mưa cao",
                    "summary": f"{day_label}: dự báo ~{pr:.0f} mm mưa" + (f", {temp_line}" if temp_line else ""),
                }
            )
        elif pr >= 40 and pb >= 70:
            alerts.append(
                {
                    "layer": "weather",
                    "severity": "watch",
                    "title": "Khả năng mưa nhiều",
                    "summary": f"{day_label}: ~{pr:.0f} mm, xác suất mưa {pb}%",
                }
            )

        if mx is not None and mx >= 37:
            alerts.append(
                {
                    "layer": "weather",
                    "severity": "warning",
                    "title": "Nắng nóng",
                    "summary": f"{day_label}: nhiệt cao nhất ~{mx:.0f}°C",
                }
            )
        elif mx is not None and mx >= 35:
            alerts.append(
                {
                    "layer": "weather",
                    "severity": "watch",
                    "title": "Trời rất nóng",
                    "summary": f"{day_label}: ~{mx:.0f}°C",
                }
            )

        if mn is not None and mn <= 10 and i == 0:
            alerts.append(
                {
                    "layer": "weather",
                    "severity": "info",
                    "title": "Rét / lạnh",
                    "summary": f"Hôm nay nhiệt thấp nhất ~{mn:.0f}°C",
                }
            )

    return alerts


def _max_severity(alerts):
    best = "ok"
    for a in alerts:
        s = a.get("severity", "info")
        if SEVERITY_ORDER.get(s, 0) > SEVERITY_ORDER.get(best, 0):
            best = s
    return best


def _provinces_in_title(title, province_names):
    """Tìm tên tỉnh xuất hiện trong tiêu đề (ưu tiên chuỗi dài trước)."""
    t = _norm(title)
    found = []
    for p in sorted(province_names, key=len, reverse=True):
        if _norm(p) in t:
            found.append(p)
            t = t.replace(_norm(p), " ")
    return found


def _news_digest_by_province(news_items, province_names, limit=3):
    """
    Tin có nhắc tên tỉnh (không cần từ khóa rủi ro) — để popup bản đồ có thêm nội dung ngoài thời tiết.
    `news_items` nên xếp mới trước (như current_data trong process_data).
    """
    out = {p: [] for p in province_names}
    counts = {p: 0 for p in province_names}
    if not news_items:
        return out
    for item in news_items:
        blob = (item.get("title") or "") + " " + (item.get("summary") or "")
        provinces = _provinces_in_title(blob, province_names)
        if not provinces:
            continue
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "")[:200]
        entry = {"title": title, "url": url}
        for p in provinces:
            if counts[p] >= limit:
                continue
            if url and any(x.get("url") == url for x in out[p]):
                continue
            out[p].append(entry)
            counts[p] += 1
    return out


def _news_alerts(news_items, province_names, locs):
    """Tầng tin: từ khóa rủi ro + tên tỉnh trong title."""
    alerts_by_province = {p: [] for p in province_names}
    if not news_items:
        return alerts_by_province

    for item in news_items:
        title = (item.get("title") or "") + " " + (item.get("summary") or "")
        nt = _norm(title)
        if not any(_norm(kw) in nt for kw in RISK_KEYWORDS):
            continue
        provinces = _provinces_in_title(title, province_names)
        if not provinces:
            continue
        for p in provinces:
            alerts_by_province[p].append(
                {
                    "layer": "news",
                    "severity": "watch",
                    "title": "Tin liên quan rủi ro",
                    "summary": (item.get("title") or "")[:200],
                    "source_url": item.get("url"),
                }
            )
    return alerts_by_province


def _one_province_job(name_lng_lat):
    name, lng, lat = name_lng_lat
    try:
        daily = _fetch_daily(lat, lng)
        w_alerts = _weather_alerts_for_province(daily)
        snap = _weather_daily_snapshot(daily)
        return name, lng, lat, w_alerts, snap, None
    except Exception as e:
        return name, lng, lat, [], [], str(e)


def rebuild_alerts_geojson(location_json_path, news_items=None, max_workers=5):
    """
    Trả về GeoJSON FeatureCollection.
    Mỗi feature: 1 tỉnh, properties.alerts là list, properties.severity là mức cao nhất.
    """
    locs = load_locations(location_json_path)
    province_names = list(locs.keys())
    jobs = [(n, locs[n][0], locs[n][1]) for n in province_names]

    weather_by_province = {}
    errors = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(_one_province_job, j) for j in jobs]
        for fut in as_completed(futs):
            name, lng, lat, w_alerts, w_snap, err = fut.result()
            weather_by_province[name] = (lng, lat, w_alerts, w_snap)
            if err:
                errors.append(f"{name}: {err}")

    news_by = _news_alerts(news_items or [], province_names, locs)
    digest_by = _news_digest_by_province(news_items or [], province_names, limit=3)

    features = []
    for name in province_names:
        got = weather_by_province.get(name)
        if got:
            lng, lat, w_alerts, w_snap = got
        else:
            lng, lat = locs[name][0], locs[name][1]
            w_alerts, w_snap = [], []
        merged = list(w_alerts) + list(news_by.get(name) or [])
        sev = _max_severity(merged)

        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": {
                    "province": name,
                    "severity": sev,
                    "alert_count": len(merged),
                    # Mapbox truyền properties dạng phẳng — cảnh báo lồng nhau gửi JSON string
                    "alerts_json": json.dumps(merged, ensure_ascii=False),
                    "weather_snapshot_json": json.dumps(w_snap, ensure_ascii=False),
                    "news_digest_json": json.dumps(digest_by.get(name) or [], ensure_ascii=False),
                },
            }
        )

    tz7 = timezone(timedelta(hours=7))
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "generated_at": datetime.now(tz7).isoformat(),
            "errors_sample": errors[:5],
            "error_count": len(errors),
        },
    }
