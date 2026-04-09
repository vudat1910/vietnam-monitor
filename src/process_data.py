import feedparser
import json
import requests
import time
import os
import re
import datetime
import warnings
import sys
import io

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))
except ImportError:
    pass 
warnings.filterwarnings("ignore")
import json as _json
from flask import Flask, Response, jsonify, request, stream_with_context, send_from_directory
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, verify_jwt_in_request
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth
import psycopg2
from psycopg2.extras import RealDictCursor
import threading
from queue import Queue

try:
    from vnstock import stock_historical_data as _vnstock_hist
    _VNSTOCK_OK = True
except Exception:
    _VNSTOCK_OK = False

try:
    import numpy as np
    import joblib
    _ML_LIBS_OK = True
except Exception:
    _ML_LIBS_OK = False

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "vm-flask-secret-2024")

app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "vietnam-monitor-secret-key-2024")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = datetime.timedelta(days=7)
jwt = JWTManager(app)

_GOOGLE_CREDS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "googles.env")
try:
    with open(_GOOGLE_CREDS_PATH) as _f:
        _gcreds = json.load(_f)["web"]
    GOOGLE_CLIENT_ID     = _gcreds["client_id"]
    GOOGLE_CLIENT_SECRET = _gcreds["client_secret"]
except Exception as _e:
    print(f"[AUTH] Không đọc được googles.env: {_e}")
    GOOGLE_CLIENT_ID = GOOGLE_CLIENT_SECRET = ""

oauth = OAuth(app)
google_oauth = oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

_DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
}

def _get_db():
    return psycopg2.connect(**_DB_CONFIG, cursor_factory=RealDictCursor)

def _init_users_table():
    """Tạo bảng users và migrate các cột mới nếu chưa có."""
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255),
                display_name VARCHAR(100),
                avatar_url VARCHAR(500),
                google_id VARCHAR(100),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        for col, definition in [
            ("avatar_url", "VARCHAR(500)"),
            ("google_id",  "VARCHAR(100)"),
        ]:
            cur.execute(f"""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {definition}
            """)
        cur.execute("""
            ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[AUTH] Bảng users đã sẵn sàng")
    except Exception as e:
        print(f"[AUTH] Lỗi tạo bảng users: {e}")

FILE_PATH = 'data.json'
processed_links = set()
current_data = []

event_queue = Queue()

_alerts_state = {"geojson": None, "updated_at": None, "lock": threading.Lock()}


def _alerts_rebuild_loop():
    """Chạy nền: gọi Open-Meteo + gắn tin rủi ro, ~45 phút/lần."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    loc_path = os.path.join(base_dir, "location.json")
    time.sleep(5)
    while True:
        try:
            import alerts_engine
            news_snapshot = list(current_data)
            gj = alerts_engine.rebuild_alerts_geojson(loc_path, news_snapshot)
            with _alerts_state["lock"]:
                _alerts_state["geojson"] = gj
                _alerts_state["updated_at"] = gj.get("meta", {}).get("generated_at")
            ec = gj.get("meta", {}).get("error_count", 0)
            print(
                f"[ALERTS] Cập nhật {len(gj.get('features', []))} tỉnh — lỗi API thời tiết: {ec}"
            )
        except Exception as e:
            print(f"[ALERTS] Lỗi rebuild: {e}")
            import traceback
            traceback.print_exc()
        time.sleep(45 * 60)

market_cache = {
    "updatedAt": None,
    "indices": {
        "VNINDEX": None,
        "VN30": None,
        "HNX": None,
        "UPCOM": None,
    },
    "source": "vnstock/TCBS"
}

INDEX_TICKERS = {
    "VNINDEX": "VNINDEX",
    "VN30": "VN30",
    "HNX": "HNX",
    "UPCOM": "UPCOM",
}

def _silent_hist(ticker, start, end, resolution):
    """Call vnstock to fetch index historical data."""
    return _vnstock_hist(ticker, start, end, resolution, type="index")

def _fetch_index(key: str, ticker: str):
    """Fetch latest index value using vnstock. Returns dict or None."""
    if not _VNSTOCK_OK:
        return None
    try:
        today = datetime.date.today().isoformat()
        week_ago = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()

        df_daily = _silent_hist(ticker, week_ago, today, "1D")
        prev_close = None
        if df_daily is not None and len(df_daily) >= 2:
            prev_close = float(df_daily["close"].iloc[-2])
            last_daily_close = float(df_daily["close"].iloc[-1])
        elif df_daily is not None and len(df_daily) == 1:
            last_daily_close = float(df_daily["close"].iloc[-1])
        else:
            return None

        try:
            df_intra = _silent_hist(ticker, today, today, "1")
            if df_intra is not None and len(df_intra) > 0:
                current = float(df_intra["close"].iloc[-1])
            else:
                current = last_daily_close
        except Exception:
            current = last_daily_close

        if prev_close and prev_close > 0:
            change = round(current - prev_close, 2)
            change_pct = round(change / prev_close * 100, 2)
        else:
            change, change_pct = None, None

        return {"price": round(current, 2), "change": change, "change_pct": change_pct}

    except Exception as e:
        print(f"[MARKET] fetch error {key}: {e}")
    return None

def market_loop():
    while True:
        out = {}
        for key, ticker in INDEX_TICKERS.items():
            out[key] = _fetch_index(key, ticker)
            print(f"[MARKET] {key}: {out[key]}")

        market_cache["indices"] = out
        market_cache["updatedAt"] = datetime.datetime.utcnow().isoformat() + "Z"
        time.sleep(60) 

if os.path.exists(FILE_PATH):
    try:
        with open(FILE_PATH, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if content:
                current_data = json.loads(content)
            else:
                current_data = []
        for item in current_data:
            if 'url' in item:
                processed_links.add(item['url'])
    except Exception as e:
        print(f"[ERROR] Load data.json: {e}")
        current_data = []

SOURCES = [
    {"name": "Dân Trí Thời Sự",     "url": "https://dantri.com.vn/rss/thoi-su.rss",     "scope": "local",  "categoryId": "p1"},
    {"name": "Dân Trí Pháp Luật",   "url": "https://dantri.com.vn/rss/phap-luat.rss",   "scope": "local",  "categoryId": "p2"},
    {"name": "Dân Trí Sức Khỏe",    "url": "https://dantri.com.vn/rss/suc-khoe.rss",    "scope": "local",  "categoryId": "p3"},
    {"name": "Dân Trí Đời Sống",    "url": "https://dantri.com.vn/rss/doi-song.rss",    "scope": "local",  "categoryId": "p4"},
    {"name": "Dân Trí Du Lịch",     "url": "https://dantri.com.vn/rss/du-lich.rss",     "scope": "local",  "categoryId": "p5"},
    {"name": "Dân Trí Kinh Doanh",  "url": "https://dantri.com.vn/rss/kinh-doanh.rss",  "scope": "local",  "categoryId": "p6"},
    {"name": "Dân Trí Bất Động Sản","url": "https://dantri.com.vn/rss/bat-dong-san.rss","scope": "local",  "categoryId": "p7"},
    {"name": "Dân Trí Thể Thao",    "url": "https://dantri.com.vn/rss/the-thao.rss",    "scope": "local",  "categoryId": "p8"},
    {"name": "Dân Trí Giải Trí",    "url": "https://dantri.com.vn/rss/giai-tri.rss",    "scope": "local",  "categoryId": "p9"},
    {"name": "Dân Trí Giáo Dục",    "url": "https://dantri.com.vn/rss/giao-duc.rss",    "scope": "local",  "categoryId": "p10"},
    {"name": "Dân Trí Nội Vụ",      "url": "https://dantri.com.vn/rss/noi-vu.rss",      "scope": "local",  "categoryId": "p11"},
    {"name": "Dân Trí Công Nghệ",   "url": "https://dantri.com.vn/rss/cong-nghe.rss",   "scope": "local",  "categoryId": "p12"},
    {"name": "VNExpress Thời Sự",   "url": "https://vnexpress.net/rss/thoi-su.rss",      "scope": "local",  "categoryId": "p1"},
    {"name": "VNExpress Kinh Doanh","url": "https://vnexpress.net/rss/kinh-doanh.rss",   "scope": "local",  "categoryId": "p6"},
    {"name": "Dân Trí Thế Giới",    "url": "https://dantri.com.vn/rss/the-gioi.rss",    "scope": "global", "categoryId": "world-news"},
    {"name": "VNExpress Thế Giới",  "url": "https://vnexpress.net/rss/the-gioi.rss",     "scope": "global", "categoryId": "world-news"},
    {"name": "Tuổi Trẻ Thế Giới",   "url": "https://tuoitre.vn/rss/the-gioi.rss",        "scope": "global", "categoryId": "world-news"},
    {"name": "BBC World",            "url": "https://feeds.bbci.co.uk/news/world/rss.xml","scope": "global", "categoryId": "world-news"},
]

_CITY_COORDS = {
    "hà nội": [105.8342, 21.0278], "tp.hcm": [106.6297, 10.8231],
    "hồ chí minh": [106.6297, 10.8231], "đà nẵng": [108.2022, 16.0544],
    "cần thơ": [105.7469, 10.0341], "hải phòng": [106.6881, 20.8449],
    "huế": [107.5905, 16.4637], "nha trang": [109.1967, 12.2388],
    "đà lạt": [108.4583, 11.9404], "vũng tàu": [107.0843, 10.3460],
}

_SEVERITY_HIGH = ["chết", "tử vong", "tai nạn", "thảm họa", "động đất",
                  "lũ lụt", "cháy", "nổ", "bắt giữ", "khởi tố", "chiến tranh"]
_SEVERITY_LOW  = ["giải trí", "du lịch", "ẩm thực", "mẹo", "review"]

def _extract_coords(text: str) -> list:
    """Tìm tọa độ từ tên địa danh trong tiêu đề/mô tả."""
    text_lower = text.lower()
    for city, coords in _CITY_COORDS.items():
        if city in text_lower:
            return coords
    return [105.8342, 21.0278]  

def _extract_severity(text: str, category_id: str) -> int:
    """Đánh giá mức độ nghiêm trọng bằng keyword, không cần LLM."""
    text_lower = text.lower()
    if any(kw in text_lower for kw in _SEVERITY_HIGH):
        return 8
    if category_id in ("p8", "p9", "p5"):  
        return 3
    if category_id in ("p2", "p11"):  
        return 7
    if any(kw in text_lower for kw in _SEVERITY_LOW):
        return 2
    return 5  

def parse_article(title, link, description, source):
    """
    Thay thế ask_ai() — không dùng LLM.
    Category lấy từ source định nghĩa sẵn (URL-based).
    Summary lấy từ RSS description.
    Severity và coords dùng keyword matching.
    """
    category_id = source.get("categoryId", "p1")
    text = f"{title} {description}"

    summary = description[:150].strip() if description else title[:100]

    return {
        "categoryId": category_id,
        "severity":   _extract_severity(text, category_id),
        "summary":    summary,
        "coords":     _extract_coords(text),
        "title":      title,
        "url":        link,
    }

def ask_ai(title, link, description, scope):
    prompt = f"""
Bạn là chuyên gia phân loại tin tức tiếng Việt. Scope: {scope}.

Nếu scope global: categoryId = "world-news".

Nếu scope local: Chọn đúng 1 trong p1 đến p12. Ưu tiên cụ thể, fallback p1 nếu không khớp rõ.

Danh mục:
- p1: Thời sự (chính trị, chính sách, lãnh đạo)
- p2: Pháp luật (vụ án, tòa án, bắt giữ, công an)
- p3: Sức khỏe (y tế, bệnh tật)
- p4: Đời sống (gia đình, mẹo vặt, hôn nhân)
- p5: Du lịch (địa điểm, kinh nghiệm du lịch)
- p6: Kinh doanh (chứng khoán, doanh nghiệp)
- p7: Bất động sản (nhà đất, dự án)
- p8: Thể thao (bóng đá, giải đấu)
- p9: Giải trí (showbiz, phim, ca nhạc, scandal)
- p10: Giáo dục (thi cử, tuyển sinh, trường học)
- p11: Nội vụ (cán bộ, tham nhũng)
- p12: Công nghệ (AI, smartphone, 5G)

Ví dụ:
- "Bắt giữ nghi phạm" → p2
- "Mẹo nấu ăn gia đình" → p4
- "Scandal ca sĩ" → p9
- "Điểm thi đại học" → p10

Đánh giá Severity (Mức độ nghiêm trọng từ 1-10):
- 1-3: Tin thường nhật, giải trí, đời sống.
- 4-6: Tin kinh tế, chính sách, giáo dục, sự cố nhỏ.
- 7-8: Tin án mạng, tai nạn nghiêm trọng, thiên tai, biến động lớn.
- 9-10: Thảm họa khẩn cấp, chiến tranh, đại dịch toàn cầu.

Xác định Tọa độ Coords [Kinh độ, Vĩ độ]:
- Tìm tên tỉnh/thành phố/quốc gia được nhắc đến. 
- Nếu ở Việt Nam, hãy trả về tọa độ trung tâm của tỉnh đó (Ví dụ: TP.HCM [106.6297, 10.8231], Đà Nẵng [108.2022, 16.0544], Cà Mau [105.1500, 9.1700]...).
- Nếu không có địa danh cụ thể, dùng mặc định Hà Nội [105.8342, 21.0278].
- ĐẢM BẢO tọa độ thực tế, không dùng số giả lập.
Tin:
Tiêu đề: {title}
Mô tả: {description}

Trả về JSON DUY NHẤT:
{{
  "categoryId": "pX or world-news",
  "severity": 5,
  "summary": "tóm tắt <20 chữ",
  "coords": [105.8342, 21.0278],
  "title": "{title}",
  "url": "{link}"
}}
"""

    print(f"[DEBUG] Gửi prompt cho: {title[:50]}... (scope: {scope})")
    try:
        response = requests.post(
            "http://127.0.0.1:11434/api/generate",
            json={
                "model": "qwen3.5:latest",
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3}
            },
            timeout=60
        )
        if response.status_code == 200:
            raw_response = response.json().get('response', '').strip()
            match = re.search(r'\{[\s\S]*\}', raw_response)
            if match:
                result = json.loads(match.group(0))
                result['title'] = title
                result['url'] = link
                return result
    except Exception as e:
        print(f"[!] Lỗi AI: {e}")
    return None

def scraper_loop():
    global current_data, processed_links
    while True:
        new_items = 0
        print("[DEBUG] Bắt đầu vòng quét...")
        for source in SOURCES:
            scope = source["scope"]
            url = source["url"]
            name = source["name"]
            print(f"[INFO] Quét {scope.upper()}: {name} - {url}")
            try:
                feed = feedparser.parse(url)
                entries = feed.entries[:5]
                for entry in entries:
                    link = entry.get('link', '').strip()
                    if not link or link in processed_links:
                        continue
                    title = entry.get('title', '').strip()
                    description = (entry.get('summary') or entry.get('description') or '').strip()
                    result = parse_article(title, link, description, source)
                    if result:
                        current_data.insert(0, result)
                        processed_links.add(link)
                        new_items += 1
                        print(f"[SUCCESS] Thêm ({result['categoryId']}): {title[:50]}...")
                        event_queue.put(json.dumps(result))
                        print(f"[DEBUG] Pushed SSE: {title[:50]}...")
            except Exception as e:
                print(f"[ERROR] Quét {url} lỗi: {e}")

        current_data = current_data[:100]
        try:
            with open(FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(current_data, f, ensure_ascii=False, indent=2)
            print(f"[SUCCESS] Lưu {len(current_data)} tin vào data.json")
        except Exception as e:
            print(f"[CRITICAL] Lưu file lỗi: {e}")

        print(f"[SUMMARY] Vòng quét xong - Tin mới: {new_items} | Nghỉ 300s...")
        time.sleep(300)

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

@app.route('/stream')
def stream():
    def generate():
        while True:
            message = event_queue.get()
            yield f"data: {message}\n\n"
    return Response(generate(), mimetype='text/event-stream')

@app.route('/data')
def get_data():
    return jsonify(current_data)

@app.route('/market')
def get_market():
    return jsonify(market_cache)

@app.route('/market/history')
def get_market_history():
    """Return 90-day daily OHLCV history for a given index symbol."""
    symbol = request.args.get('symbol', 'VNINDEX').upper()
    ticker_map = {'VNINDEX': 'VNINDEX', 'VN30': 'VN30', 'HNX': 'HNX', 'UPCOM': 'UPCOM'}
    ticker = ticker_map.get(symbol, 'VNINDEX')
    if not _VNSTOCK_OK:
        return jsonify({'symbol': symbol, 'data': []})
    try:
        end = datetime.date.today().isoformat()
        start = (datetime.date.today() - datetime.timedelta(days=120)).isoformat()
        df = _vnstock_hist(ticker, start, end, '1D', type='index')
        if df is not None and len(df) > 0:
            rows = []
            for _, row in df.iterrows():
                t = str(row.get('time', ''))[:10]
                if t:
                    rows.append({'time': t, 'value': round(float(row['close']), 2)})
            return jsonify({'symbol': symbol, 'data': rows})
    except Exception as e:
        print(f"[MARKET HISTORY] {symbol}: {e}")
    return jsonify({'symbol': symbol, 'data': []})

@app.route('/stock/history')
def get_stock_history():
    """Return daily OHLCV history for any individual stock (e.g. VNM, FPT)."""
    symbol = request.args.get('symbol', 'VNM').upper()
    range_param = request.args.get('range', '3M')
    if not _VNSTOCK_OK:
        return jsonify({'symbol': symbol, 'data': []})
    days_map = {'1M': 35, '3M': 95, '1Y': 380, '2Y': 740}
    days = days_map.get(range_param, 95)
    try:
        end = datetime.date.today().isoformat()
        start = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        df = _vnstock_hist(symbol, start, end, '1D')
        if df is not None and len(df) > 0:
            rows = []
            for _, row in df.iterrows():
                t = str(row.get('time', ''))[:10]
                if not t:
                    continue
                rows.append({
                    'time': t,
                    'open':  round(float(row['open']),  2),
                    'high':  round(float(row['high']),  2),
                    'low':   round(float(row['low']),   2),
                    'close': round(float(row['close']), 2),
                    'volume': int(row.get('volume', 0)),
                })
            return jsonify({'symbol': symbol, 'data': rows})
    except Exception as e:
        print(f"[STOCK HISTORY] {symbol}: {e}")
    return jsonify({'symbol': symbol, 'data': [], 'error': 'Không tìm thấy mã'})

def _parse_sjc_prices():
    """Scrape SJC gold buy/sell prices from sjc.com.vn."""
    urls = [
        'https://sjc.com.vn/GiaVang/Index',
        'https://sjc.com.vn/gia-vang',
        'https://sjc.com.vn/',
    ]
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    for url in urls:
        try:
            resp = requests.get(url, timeout=10, headers=headers)
            resp.encoding = 'utf-8'
            text = resp.text
            rows = re.findall(
                r'<tr[^>]*>.*?<td[^>]*>(.*?)</td>.*?<td[^>]*>(.*?)</td>.*?<td[^>]*>(.*?)</td>.*?</tr>',
                text, re.DOTALL
            )
            results = []
            for name_raw, buy_raw, sell_raw in rows:
                name = re.sub(r'<[^>]+>', '', name_raw).strip()
                buy_s  = re.sub(r'[^\d]', '', buy_raw)
                sell_s = re.sub(r'[^\d]', '', sell_raw)
                if name and buy_s and sell_s and len(buy_s) >= 5:
                    try:
                        buy_v  = int(buy_s)
                        sell_v = int(sell_s)
                        if buy_v < 1_000_000:
                            buy_v  *= 1000
                            sell_v *= 1000
                        results.append({'name': name, 'buy': buy_v, 'sell': sell_v})
                    except Exception:
                        pass
            if results:
                return results
        except Exception as e:
            print(f"[GOLD SJC] {url}: {e}")
    return []


def _parse_doji_prices():
    """Scrape DOJI gold prices from doji.vn."""
    try:
        resp = requests.get('https://doji.vn/bang-gia-vang/', timeout=10,
                            headers={'User-Agent': 'Mozilla/5.0'})
        resp.encoding = 'utf-8'
        text = resp.text
        rows = re.findall(
            r'<tr[^>]*>.*?<td[^>]*>(.*?)</td>.*?<td[^>]*>(.*?)</td>.*?<td[^>]*>(.*?)</td>.*?</tr>',
            text, re.DOTALL
        )
        results = []
        for name_raw, buy_raw, sell_raw in rows:
            name  = re.sub(r'<[^>]+>', '', name_raw).strip()
            buy_s  = re.sub(r'[^\d]', '', buy_raw)
            sell_s = re.sub(r'[^\d]', '', sell_raw)
            if name and buy_s and sell_s and len(buy_s) >= 5:
                try:
                    buy_v  = int(buy_s)
                    sell_v = int(sell_s)
                    if buy_v < 1_000_000:
                        buy_v  *= 1000
                        sell_v *= 1000
                    results.append({'name': name, 'buy': buy_v, 'sell': sell_v})
                except Exception:
                    pass
        return results
    except Exception as e:
        print(f"[GOLD DOJI] {e}")
    return []


@app.route('/commodity/gold/current')
def get_gold_current():
    """Fetch live gold prices from SJC + DOJI."""
    now_str = datetime.datetime.now().strftime('%H:%M %d/%m/%Y')
    sources = {}

    sjc  = _parse_sjc_prices()
    doji = _parse_doji_prices()

    if sjc:  sources['SJC']  = sjc
    if doji: sources['DOJI'] = doji

    return jsonify({'sources': sources, 'updatedAt': now_str})


@app.route('/commodity/gold/history')
def get_gold_history():
    """Historical gold price: XAU/USD từ Yahoo Finance, convert sang VND/lượng."""
    OZ_TO_TAEL = 37.5 / 31.1035  
    USD_VND    = 25500
    try:
        url  = 'https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=1y'
        resp = requests.get(url, timeout=12, headers={'User-Agent': 'Mozilla/5.0'})
        j    = resp.json()
        result    = j['chart']['result'][0]
        timestamps = result['timestamp']
        closes     = result['indicators']['quote'][0]['close']
        rows = []
        for ts, c in zip(timestamps, closes):
            if c is None:
                continue
            date_str  = datetime.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d')
            vnd_tael  = round(c * OZ_TO_TAEL * USD_VND)
            rows.append({'time': date_str, 'value': vnd_tael})
        rows = sorted(rows, key=lambda x: x['time'])
        if rows:
            return jsonify({'unit': 'VND/lượng', 'data': rows})
    except Exception as e:
        print(f"[GOLD HISTORY] {e}")
    return jsonify({'unit': 'VND/lượng', 'data': []})


def _scrape_pvoil_prices():
    """Scrape current retail fuel prices from PVOIL website."""
    try:
        resp = requests.get('https://pvoil.com.vn', timeout=12,
                            headers={'User-Agent': 'Mozilla/5.0'})
        resp.encoding = 'utf-8'
        text = resp.text
        # Find the price section
        idx = text.find('B&#7843;ng gi&#225; b&#225;n l&#7867;')
        if idx == -1:
            idx = text.find('Bảng giá bán lẻ')
        if idx == -1:
            idx = text.find('B&agrave;ng gi&aacute;')
        chunk = text[max(0, idx):idx + 5000] if idx != -1 else text

        items = re.findall(
            r'(?:Xăng|Dầu|Xang|Dau)\s+[^\n<]{3,40}?[\s\S]{0,300}?(\d{2,3}[.,]\d{3})\s*(?:đ|d)',
            chunk
        )
        labels = re.findall(r'((?:Xăng|Dầu)[^<\n]{3,50})', chunk)
        prices = re.findall(r'(\d{2,3}[.,]\d{3})\s*(?:đ\b)', chunk)

        result = {}
        for i, label in enumerate(labels):
            if i < len(prices):
                label_clean = re.sub(r'\s+', ' ', label).strip()
                price_val   = int(prices[i].replace('.', '').replace(',', ''))
                result[label_clean] = price_val

        if result:
            return result
    except Exception as e:
        print(f"[PVOIL SCRAPE] {e}")
    return {}


@app.route('/commodity/fuel/current')
def get_fuel_current():
    """Return live PVOIL fuel retail prices."""
    data = _scrape_pvoil_prices()
    fallback = {
        'Xăng RON 95-III':    25570,
        'Xăng E10 RON 95-III':24060,
        'Xăng E5 RON 92-II':  22500,
        'Dầu DO 0,05S-II':    27020,
        'Dầu DO 0,001S-V':    27220,
    }
    if not data:
        data = fallback
    return jsonify({'prices': data,
                    'updatedAt': datetime.datetime.now().strftime('%H:%M %d/%m/%Y'),
                    'source': 'PVOIL'})


@app.route('/commodity/fuel')
def get_fuel_history():
    """Return Vietnam retail petroleum prices for all types (VND/lít).
       Source: Bộ Công Thương điều hành giá xăng dầu (government-announced prices).
       Prices adjusted every ~10 days. 5 product types tracked.
    """
    schedule = [
        ('2024-01-11', [24035, None,  22440, 20516, 20716]),
        ('2024-01-25', [23924, None,  22340, 20456, 20656]),
        ('2024-02-08', [23748, None,  22174, 20299, 20499]),
        ('2024-02-22', [23629, None,  22065, 20154, 20354]),
        ('2024-03-07', [23551, None,  21995, 20082, 20282]),
        ('2024-03-21', [23802, None,  22230, 20269, 20469]),
        ('2024-04-04', [24145, None,  22554, 20575, 20775]),
        ('2024-04-18', [24601, None,  22981, 20957, 21157]),
        ('2024-05-02', [25011, None,  23369, 21298, 21498]),
        ('2024-05-16', [25014, None,  23372, 21300, 21500]),
        ('2024-06-01', [24528, None,  22908, 20874, 21074]),
        ('2024-06-13', [23855, None,  22277, 20297, 20497]),
        ('2024-06-27', [23117, None,  21586, 19693, 19893]),
        ('2024-07-11', [23488, None,  21933, 19987, 20187]),
        ('2024-07-25', [22740, None,  21234, 19352, 19552]),
        ('2024-08-01', [22560, None,  21070, 22100, 22300]),
        ('2024-08-15', [22043, None,  20577, 23410, 23610]),
        ('2024-08-29', [21726, None,  20278, 23140, 23340]),
        ('2024-09-05', [21450, None,  20022, 24060, 24260]),
        ('2024-09-19', [21576, None,  20140, 24190, 24390]),
        ('2024-10-03', [21532, None,  20100, 24150, 24350]),
        ('2024-10-17', [21856, None,  20398, 24460, 24660]),
        ('2024-10-31', [22274, None,  20790, 24870, 25070]),
        ('2024-11-14', [22155, None,  20676, 24750, 24950]),
        ('2024-11-28', [22155, None,  20676, 24750, 24950]),
        ('2024-12-12', [22546, None,  21044, 25140, 25340]),
        ('2024-12-26', [22694, None,  21188, 25300, 25500]),
        ('2025-01-09', [22967, None,  21444, 25590, 25790]),
        ('2025-01-16', [22854, None,  21337, 25470, 25670]),
        ('2025-01-23', [23062, None,  21536, 25690, 25890]),
        ('2025-02-06', [22793, None,  21280, 25410, 25610]),
        ('2025-02-20', [22477, None,  20981, 25090, 25290]),
        ('2025-03-06', [22136, None,  20659, 24750, 24950]),
        ('2025-03-20', [21807, None,  20346, 24410, 24610]),
        ('2025-04-03', [21353, None,  19920, 23950, 24150]),
        ('2025-04-17', [20934, None,  19524, 23520, 23720]),
        ('2025-05-01', [20508, None,  19121, 23090, 23290]),
        ('2025-05-15', [20686, None,  19290, 23270, 23470]),
        ('2025-05-29', [21020, None,  19606, 23600, 23800]),
        ('2025-06-12', [21296, None,  19868, 23880, 24080]),
        ('2025-06-26', [21600, None,  20155, 24190, 24390]),
        ('2025-07-10', [21460, None,  20022, 24050, 24250]),
        ('2025-07-24', [21822, None,  20363, 24420, 24620]),
        ('2025-08-07', [22186, None,  20706, 24790, 24990]),
        ('2025-08-21', [22552, None,  21048, 25160, 25360]),
        ('2025-09-04', [22250, None,  20761, 24860, 25060]),
        ('2025-09-18', [21930, None,  20456, 24530, 24730]),
        ('2025-10-02', [21696, None,  20233, 24290, 24490]),
        ('2025-10-16', [21451, None,  20001, 24040, 24240]),
        ('2025-10-30', [21789, None,  20325, 24380, 24580]),
        ('2025-11-13', [22160, None,  20676, 24760, 24960]),
        ('2025-11-27', [22498, None,  20996, 25100, 25300]),
        ('2025-12-11', [22764, None,  21249, 25370, 25570]),
        ('2025-12-25', [22924, None,  21400, 25540, 25740]),
        ('2026-01-09', [23060, None,  21528, 25680, 25880]),
        ('2026-01-23', [22897, None,  21374, 25510, 25710]),
        ('2026-02-06', [22654, None,  21143, 25260, 25460]),
        ('2026-02-20', [22425, None,  20927, 25030, 25230]),
        ('2026-03-06', [22705, None,  21190, 25310, 25510]),
        ('2026-03-13', [25570, 24060, 22500, 27020, 27220]),
    ]

    fuel_types = [
        {'key': 'ron95',    'label': 'Xăng RON 95-III',     'color': '#3b82f6'},
        {'key': 'e10ron95', 'label': 'Xăng E10 RON 95-III', 'color': '#0ea5e9'},
        {'key': 'e5ron92',  'label': 'Xăng E5 RON 92-II',   'color': '#10b981'},
        {'key': 'do005',    'label': 'Dầu DO 0,05S-II',     'color': '#f59e0b'},
        {'key': 'do0001',   'label': 'Dầu DO 0,001S-V',     'color': '#ef4444'},
    ]

    result = {ft['key']: {'label': ft['label'], 'color': ft['color'], 'data': []} for ft in fuel_types}
    keys   = [ft['key'] for ft in fuel_types]
    for date, prices in schedule:
        for i, k in enumerate(keys):
            if prices[i] is not None:
                result[k]['data'].append({'time': date, 'value': prices[i]})

    return jsonify({'types': fuel_types, 'series': result, 'unit': 'VND/lít',
                    'note': 'Nguồn: MOIT & PVOIL. Giá điều hành nhà nước.'})

_ML_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ml')
_ml_clf   = None
_ml_reg   = None
_ml_scaler = None
_ml_meta  = None
_ML_OK    = False

def _load_ml_models():
    global _ml_clf, _ml_reg, _ml_scaler, _ml_meta, _ML_OK
    if not _ML_LIBS_OK:
        return
    try:
        _ml_clf    = joblib.load(os.path.join(_ML_DIR, 'model_clf.pkl'))
        _ml_reg    = joblib.load(os.path.join(_ML_DIR, 'model_reg.pkl'))
        _ml_scaler = joblib.load(os.path.join(_ML_DIR, 'scaler.pkl'))
        with open(os.path.join(_ML_DIR, 'metadata.json'), encoding='utf-8') as f:
            _ml_meta = json.load(f)
        _ML_OK = True
        print(f"[ML] Model loaded — acc={_ml_meta['accuracy']:.2%}, "
              f"trained={_ml_meta['trained_at'][:10]}, "
              f"stocks={_ml_meta['n_stocks']}")
    except Exception as e:
        print(f"[ML] Model not found ({e}). Run: python3 ml/train_model.py")

_load_ml_models()

_ml_gold_clf    = None
_ml_gold_reg    = None
_ml_gold_scaler = None
_ml_gold_meta   = None
_ML_GOLD_OK     = False

_gold_pred_cache = None
_gold_pred_lock  = threading.Lock()

def _load_gold_models():
    global _ml_gold_clf, _ml_gold_reg, _ml_gold_scaler, _ml_gold_meta, _ML_GOLD_OK
    if not _ML_LIBS_OK:
        return
    try:
        _ml_gold_clf    = joblib.load(os.path.join(_ML_DIR, 'model_gold_clf.pkl'))
        _ml_gold_reg    = joblib.load(os.path.join(_ML_DIR, 'model_gold_reg.pkl'))
        _ml_gold_scaler = joblib.load(os.path.join(_ML_DIR, 'scaler_gold.pkl'))
        with open(os.path.join(_ML_DIR, 'metadata_gold.json'), encoding='utf-8') as f:
            _ml_gold_meta = json.load(f)
        _ML_GOLD_OK = True
        print(f"[ML-Gold] Model loaded — acc={_ml_gold_meta['accuracy']:.2%}, "
              f"trained={_ml_gold_meta['trained_at'][:10]}")
    except Exception as e:
        print(f"[ML-Gold] Model not found ({e}). Run: train_model_gold.ipynb")

_load_gold_models()

def _compute_gold_features(df_gold, df_silver=None, df_usd=None, df_tnx=None, df_oil=None, df_vix=None):
    """Compute 28 features for gold prediction — must match train_model_gold.ipynb."""
    import pandas as _pd
    df = df_gold.copy()
    if isinstance(df.columns, _pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df.sort_index().dropna()

    df['ret_1']  = df['close'].pct_change(1)  * 100
    df['ret_3']  = df['close'].pct_change(3)  * 100
    df['ret_5']  = df['close'].pct_change(5)  * 100
    df['ret_10'] = df['close'].pct_change(10) * 100
    df['ret_20'] = df['close'].pct_change(20) * 100
    df['ema5']   = df['close'].ewm(span=5,  adjust=False).mean()
    df['ema20']  = df['close'].ewm(span=20, adjust=False).mean()
    df['ema5_ratio']  = (df['close'] / df['ema5']  - 1) * 100
    df['ema20_ratio'] = (df['close'] / df['ema20'] - 1) * 100
    df['ema5_ema20']  = (df['ema5']  / df['ema20'] - 1) * 100
    delta    = df['close'].diff()
    avg_gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    df['rsi'] = 100 - 100 / (1 + avg_gain / (avg_loss + 1e-9))
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    df['macd_hist'] = (macd - macd.ewm(span=9, adjust=False).mean()) / df['close'] * 100
    ma20  = df['close'].rolling(20).mean()
    std20 = df['close'].rolling(20).std()
    df['bb_pos']    = ((df['close'] - (ma20 - 2*std20)) / (4*std20 + 1e-9)).clip(0, 1)
    df['atr_ratio'] = (df['high'] - df['low']) / df['close'] * 100
    if 'volume' in df.columns and df['volume'].sum() > 0:
        df['vol_ratio'] = df['volume'] / (df['volume'].rolling(20).mean() + 1)
    else:
        df['vol_ratio'] = 1.0
    low14  = df['low'].rolling(14).min()
    high14 = df['high'].rolling(14).max()
    df['stoch_k']    = ((df['close'] - low14) / (high14 - low14 + 1e-9) * 100).clip(0, 100)
    df['williams_r'] = ((high14 - df['close']) / (high14 - low14 + 1e-9) * -100).clip(-100, 0)
    high20 = df['high'].rolling(20).max()
    low20  = df['low'].rolling(20).min()
    df['high20_dist'] = (df['close'] / high20 - 1) * 100
    df['low20_dist']  = (df['close'] / low20  - 1) * 100

    def _add_macro(df, col1, col3, col5, df_m):
        import pandas as _pd2
        if df_m is None:
            df[col1] = df[col3] = 0.0
            if col5: df[col5] = 0.0
            return
        dm = df_m.copy()
        if isinstance(dm.columns, _pd2.MultiIndex):
            dm.columns = dm.columns.get_level_values(0)
        dm.columns = [c.lower() for c in dm.columns]
        c = dm['close'].reindex(df.index, method='ffill')
        df[col1] = c.pct_change(1) * 100
        df[col3] = c.pct_change(3) * 100
        if col5: df[col5] = c.pct_change(5) * 100

    _add_macro(df, 'usd_ret1', 'usd_ret3', 'usd_ret5', df_usd)
    _add_macro(df, 'tnx_ret1', 'tnx_ret3',  None,      df_tnx)
    _add_macro(df, 'oil_ret1', 'oil_ret3',  None,       df_oil)

    if df_vix is not None:
        import pandas as _pd3
        dv = df_vix.copy()
        if isinstance(dv.columns, _pd3.MultiIndex):
            dv.columns = dv.columns.get_level_values(0)
        dv.columns = [c.lower() for c in dv.columns]
        vc = dv['close'].reindex(df.index, method='ffill')
        df['vix_ret1']  = vc.pct_change(1) * 100
        df['vix_level'] = vc / 100
    else:
        df['vix_ret1'] = df['vix_level'] = 0.0

    if df_silver is not None:
        import pandas as _pd4
        ds = df_silver.copy()
        if isinstance(ds.columns, _pd4.MultiIndex):
            ds.columns = ds.columns.get_level_values(0)
        ds.columns = [c.lower() for c in ds.columns]
        sc = ds['close'].reindex(df.index, method='ffill')
        gs_raw = df['close'] / (sc + 1e-9)
        gs_ma  = gs_raw.rolling(60).mean()
        df['gs_ratio'] = (gs_raw / gs_ma - 1) * 100
    else:
        df['gs_ratio'] = 0.0

    return df

_FEAT_VI = {
    'ret_1':        '% thay đổi 1 ngày',
    'ret_3':        '% thay đổi 3 ngày',
    'ret_5':        '% thay đổi 5 ngày',
    'ret_10':       '% thay đổi 10 ngày',
    'ret_20':       '% thay đổi 20 ngày',
    'ema5_ratio':   'Giá / EMA5',
    'ema20_ratio':  'Giá / EMA20',
    'ema5_ema20':   'EMA5 / EMA20',
    'rsi':          'RSI(14)',
    'macd_hist':    'MACD Histogram',
    'bb_pos':       'Vị trí Bollinger',
    'atr_ratio':    'Biên độ ATR',
    'vol_ratio':    'Tỷ lệ Volume',
    'stoch_k':      'Stochastic %K',
    'williams_r':   'Williams %R',
    'high20_dist':  '% cách đỉnh 20 ngày',
    'low20_dist':   '% cách đáy 20 ngày',
}

def _compute_ml_features(df):
    """Compute technical indicator features — must stay in sync with train_model.ipynb."""
    df = df.copy().sort_values('time').reset_index(drop=True)

    df['ret_1']  = df['close'].pct_change(1)  * 100
    df['ret_3']  = df['close'].pct_change(3)  * 100
    df['ret_5']  = df['close'].pct_change(5)  * 100
    df['ret_10'] = df['close'].pct_change(10) * 100
    df['ret_20'] = df['close'].pct_change(20) * 100

    df['ema5']  = df['close'].ewm(span=5,  adjust=False).mean()
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema5_ratio']  = (df['close'] / df['ema5']  - 1) * 100
    df['ema20_ratio'] = (df['close'] / df['ema20'] - 1) * 100
    df['ema5_ema20']  = (df['ema5']  / df['ema20'] - 1) * 100

    delta    = df['close'].diff()
    avg_gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    df['rsi'] = 100 - 100 / (1 + avg_gain / (avg_loss + 1e-9))

    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    df['macd_hist'] = (macd - macd.ewm(span=9, adjust=False).mean()) / df['close'] * 100

    ma20  = df['close'].rolling(20).mean()
    std20 = df['close'].rolling(20).std()
    df['bb_pos'] = ((df['close'] - (ma20 - 2*std20)) / (4*std20 + 1e-9)).clip(0, 1)

    df['atr_ratio'] = (df['high'] - df['low']) / df['close'] * 100

    if 'volume' in df.columns and df['volume'].sum() > 0:
        vol_ma = df['volume'].rolling(20).mean()
        df['vol_ratio'] = df['volume'] / (vol_ma + 1)
    else:
        df['vol_ratio'] = 1.0

    low14  = df['low'].rolling(14).min()
    high14 = df['high'].rolling(14).max()
    df['stoch_k'] = ((df['close'] - low14) / (high14 - low14 + 1e-9) * 100).clip(0, 100)

    df['williams_r'] = ((high14 - df['close']) / (high14 - low14 + 1e-9) * -100).clip(-100, 0)

    high20 = df['high'].rolling(20).max()
    low20  = df['low'].rolling(20).min()
    df['high20_dist'] = (df['close'] / high20 - 1) * 100
    df['low20_dist']  = (df['close'] / low20  - 1) * 100

    return df

@app.route('/ml/predict')
def ml_predict():
    if not _ML_OK:
        return jsonify({
            'error': 'Model chưa được train. Chạy: python3 ml/train_model.py',
            'ready': False
        }), 503

    symbol = request.args.get('symbol', 'VNM').upper()

    if not _VNSTOCK_OK:
        return jsonify({'error': 'vnstock không khả dụng', 'symbol': symbol}), 503

    try:
        end   = datetime.date.today().isoformat()
        start = (datetime.date.today() - datetime.timedelta(days=120)).isoformat()
        is_index = symbol in ('VNINDEX', 'VN30', 'HNX', 'UPCOM')

        # Fetch OHLCV
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = io.StringIO()
        try:
            if is_index:
                df = _vnstock_hist(symbol, start, end, '1D', type='index')
            else:
                df = _vnstock_hist(symbol, start, end, '1D')
        finally:
            sys.stdout, sys.stderr = old_out, old_err

        if df is None or len(df) < 30:
            return jsonify({'error': f'Không đủ dữ liệu cho {symbol}', 'symbol': symbol}), 404

        df = _compute_ml_features(df)

        FEATURES = _ml_meta['features']
        feats_ok = [f for f in FEATURES if f in df.columns]
        df_feat  = df[feats_ok].dropna()

        if df_feat.empty:
            return jsonify({'error': 'Không tính được features', 'symbol': symbol}), 500

        X_today  = df_feat.iloc[[-1]].values
        X_scaled = _ml_scaler.transform(X_today)

        pred_cls   = int(_ml_clf.predict(X_scaled)[0])
        proba      = _ml_clf.predict_proba(X_scaled)[0]
        classes    = _ml_clf.classes_.tolist()
        confidence = float(proba[classes.index(pred_cls)]) * 100
        pred_ret   = float(_ml_reg.predict(X_scaled)[0])

        dir_map = {1: 'TĂNG', 0: 'ĐI NGANG', -1: 'GIẢM'}

        feat_imp = _ml_meta.get('feature_importances', {})
        top3 = sorted(feat_imp.items(), key=lambda x: -x[1])[:3]

        return jsonify({
            'symbol':           symbol,
            'direction':        dir_map[pred_cls],
            'direction_code':   pred_cls,
            'confidence':       round(confidence, 1),
            'predicted_return': round(pred_ret, 2),
            'horizon':          _ml_meta['horizon'],
            'model_accuracy':   round(_ml_meta['accuracy'] * 100, 1),
            'n_stocks_trained': _ml_meta['n_stocks'],
            'trained_at':       _ml_meta['trained_at'][:10],
            'current_price':    int(df['close'].iloc[-1]),
            'top_features': [
                {'name': _FEAT_VI.get(f, f), 'importance': round(v * 100, 1)}
                for f, v in top3
            ],
            'ready': True,
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e), 'symbol': symbol}), 500

def _compute_gold_prediction():
    """Tính dự đoán vàng và lưu vào cache. Gọi lúc khởi động và mỗi giờ."""
    global _gold_pred_cache
    if not _ML_GOLD_OK:
        return
    try:
        import yfinance as yf
        import pandas as _pd

        def _fetch(ticker, period='180d'):
            df = yf.download(ticker, period=period, interval='1d', progress=False)
            if isinstance(df.columns, _pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            return df.dropna()

        print('[ML-Gold] Đang tải dữ liệu thị trường để dự đoán...')
        df_gold   = _fetch('GC=F')
        df_silver = _fetch('SI=F')
        df_usd    = _fetch('DX-Y.NYB')
        df_tnx    = _fetch('^TNX')
        df_oil    = _fetch('CL=F')
        df_vix    = _fetch('^VIX')

        if df_gold is None or len(df_gold) < 30:
            print('[ML-Gold] Không đủ dữ liệu vàng')
            return

        df_feat = _compute_gold_features(df_gold, df_silver, df_usd, df_tnx, df_oil, df_vix)
        FEATURES = _ml_gold_meta['features']
        df_ready = df_feat[FEATURES].dropna()
        if df_ready.empty:
            print('[ML-Gold] Không tính được features — thử tăng period')
            return
        row = df_ready.iloc[[-1]]

        X_scaled = _ml_gold_scaler.transform(row.values)
        pred_cls   = int(_ml_gold_clf.predict(X_scaled)[0])
        proba      = _ml_gold_clf.predict_proba(X_scaled)[0]
        classes    = _ml_gold_clf.classes_.tolist()
        confidence = round(proba[classes.index(pred_cls)] * 100, 1)
        pred_ret   = round(float(_ml_gold_reg.predict(X_scaled)[0]), 2)

        dir_map    = {1: 'TĂNG', -1: 'GIẢM', 0: 'ĐI NGANG'}
        gold_price = float(df_gold['close'].iloc[-1])

        feat_imp = _ml_gold_meta.get('feature_importances', {})
        top3 = sorted(feat_imp.items(), key=lambda x: x[1], reverse=True)[:3]

        result = {
            'ready':            True,
            'direction':        dir_map.get(pred_cls, '?'),
            'direction_code':   pred_cls,
            'confidence':       confidence,
            'predicted_return': pred_ret,
            'horizon':          _ml_gold_meta.get('horizon', 5),
            'model_accuracy':   round(_ml_gold_meta['accuracy'] * 100, 1),
            'gold_price_usd':   round(gold_price, 1),
            'top_features': [
                {'name': _FEAT_VI.get(f, f), 'importance': round(v * 100, 1)}
                for f, v in top3
            ],
            'cached_at': datetime.datetime.now().strftime('%H:%M %d/%m/%Y'),
        }

        with _gold_pred_lock:
            _gold_pred_cache = result
        print(f'[ML-Gold] Cache cập nhật — {result["direction"]} {confidence}%')

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f'[ML-Gold] Lỗi compute: {e}')


def _gold_prediction_loop():
    """Background thread: tính lại dự đoán vàng mỗi giờ."""
    import time
    _compute_gold_prediction()
    while True:
        time.sleep(3600)  
        _compute_gold_prediction()


@app.route('/ml/predict-gold')
def ml_predict_gold():
    if not _ML_GOLD_OK:
        return jsonify({'error': 'Model vàng chưa train. Chạy train_model_gold.ipynb', 'ready': False}), 503
    with _gold_pred_lock:
        cache = _gold_pred_cache
    if cache is None:
        return jsonify({'ready': False, 'error': 'Đang tính toán dự đoán, vui lòng thử lại sau 30 giây...'}), 503
    return jsonify(cache)

@app.route('/ml/status')
def ml_status():
    if not _ML_OK:
        return jsonify({'ready': False, 'message': 'Chưa train model'})
    return jsonify({
        'ready':      True,
        'accuracy':   round(_ml_meta['accuracy'] * 100, 1),
        'n_stocks':   _ml_meta['n_stocks'],
        'n_samples':  _ml_meta['n_samples'],
        'trained_at': _ml_meta['trained_at'][:10],
    })

_fuel_pred_cache = None
_fuel_pred_ts    = 0
_FUEL_CACHE_TTL  = 1800  # 30 phút

@app.route('/ml/predict-fuel')
def ml_predict_fuel():
    """Dự đoán chiều điều chỉnh giá xăng dầu kỳ tới dựa trên WTI/Brent + USD."""
    global _fuel_pred_cache, _fuel_pred_ts
    if _fuel_pred_cache and (time.time() - _fuel_pred_ts) < _FUEL_CACHE_TTL:
        return jsonify(_fuel_pred_cache)
    try:
        import yfinance as yf
        import pandas as _pd

        def _fetch_safe(ticker, period='60d'):
            try:
                df = yf.download(ticker, period=period, interval='1d', progress=False)
                if df is None or df.empty:
                    return None
                if isinstance(df.columns, _pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df.columns = [c.lower() for c in df.columns]
                df = df[['close']].dropna()
                return df if len(df) >= 22 else None
            except Exception:
                return None

        df_wti = _fetch_safe('CL=F')
        if df_wti is None:
            return jsonify({'error': 'Không lấy được giá dầu WTI', 'ready': False}), 503

        df_brent = _fetch_safe('BZ=F')
        df_usd   = _fetch_safe('DX-Y.NYB')

        def _ret10(series):
            """% thay đổi trung bình 10 ngày gần nhất so với 10 ngày trước."""
            now  = float(series.iloc[-10:].mean())
            prev = float(series.iloc[-20:-10].mean())
            return (now - prev) / prev * 100 if prev != 0 else 0.0

        wti_ret = _ret10(df_wti['close'])

        if df_brent is not None:
            brent_ret = _ret10(df_brent['close'])
            brent_price = round(float(df_brent['close'].iloc[-1]), 2)
            brent_ok = True
        else:
            brent_ret = wti_ret  
            brent_price = None
            brent_ok = False

        if df_usd is not None:
            usd_ret = _ret10(df_usd['close'])
        else:
            usd_ret = 0.0

        if brent_ok:
            combined_impact = wti_ret * 0.45 + brent_ret * 0.35 + usd_ret * 0.20
        else:
            combined_impact = wti_ret * 0.80 + usd_ret * 0.20

        THRESHOLD = 1.5
        if combined_impact > THRESHOLD:
            direction_code = 1
            direction = 'TĂNG'
            confidence = min(95, 50 + abs(combined_impact) * 5)
        elif combined_impact < -THRESHOLD:
            direction_code = -1
            direction = 'GIẢM'
            confidence = min(95, 50 + abs(combined_impact) * 5)
        else:
            direction_code = 0
            direction = 'ĐI NGANG'
            confidence = max(40, 60 - abs(combined_impact) * 5)

        est_change_pct = round(combined_impact * 0.7, 2)

        today = datetime.datetime.now()
        days_to_thursday = (3 - today.weekday()) % 7
        if days_to_thursday == 0:
            days_to_thursday = 7
        next_adj = today + datetime.timedelta(days=days_to_thursday)

        factors = [{'name': 'Dầu WTI (10 ngày)', 'value': round(wti_ret, 2)}]
        if brent_ok:
            factors.append({'name': 'Dầu Brent (10 ngày)', 'value': round(brent_ret, 2)})
        factors.append({'name': 'USD Index (10 ngày)', 'value': round(usd_ret, 2)})

        result = {
            'ready':           True,
            'direction':       direction,
            'direction_code':  direction_code,
            'confidence':      round(confidence, 1),
            'combined_impact': round(combined_impact, 2),
            'est_change_pct':  est_change_pct,
            'next_adj_date':   next_adj.strftime('%d/%m/%Y'),
            'wti_price':       round(float(df_wti['close'].iloc[-1]), 2),
            'wti_ret':         round(wti_ret, 2),
            'brent_price':     brent_price,
            'brent_ret':       round(brent_ret, 2) if brent_ok else None,
            'usd_ret':         round(usd_ret, 2),
            'factors':         factors,
        }
        _fuel_pred_cache = result
        _fuel_pred_ts    = time.time()
        return jsonify(result)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e), 'ready': False}), 500



def _re_get_conn():
    """Dùng đúng get_conn() như scrapers.py — tránh lệch cấu hình DB."""
    try:
        _re_path = os.path.join(os.path.dirname(__file__), "real_estate")
        if _re_path not in sys.path:
            sys.path.insert(0, _re_path)
        from db import get_conn
        return get_conn()
    except Exception as e:
        print(f"[RE] Không kết nối được PostgreSQL: {e}")
        return None

@app.route('/re/listings')
def re_listings():
    city         = request.args.get('city', '')
    listing_type = request.args.get('type', '')
    category     = request.args.get('category', '')
    q            = request.args.get('q', '')
    page         = int(request.args.get('page', 1))
    per_page     = int(request.args.get('per_page', 20))
    offset       = (page - 1) * per_page

    conn = _re_get_conn()
    if not conn:
        return jsonify({'error': 'Không kết nối được DB', 'items': [], 'total': 0}), 500

    filters = ["COALESCE(is_active, true) = true"]
    params  = []

    if city:
        filters.append("city = %s")
        params.append(city)
    if listing_type:
        filters.append("listing_type = %s")
        params.append(listing_type)
    if category:
        filters.append("category = %s")
        params.append(category)
    if q:
        filters.append("(title ILIKE %s OR address ILIKE %s OR project_name ILIKE %s)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]

    where = "WHERE " + " AND ".join(filters)

    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) as cnt FROM re_listings {where}", params)
        total = cur.fetchone()['cnt']

        cur.execute(
            f"""SELECT id, source, external_id, listing_tier, title,
                       price, price_text, price_per_m2, area,
                       address, ward, district, city,
                       listing_type, category,
                       bedrooms, bathrooms, floor,
                       direction, legal, furniture,
                       project_name, contact_name, contact_phone,
                       images_json, source_url, posted_at, scraped_at
                FROM re_listings {where}
                ORDER BY COALESCE(posted_at, scraped_at) DESC NULLS LAST,
                         scraped_at DESC
                LIMIT %s OFFSET %s""",
            params + [per_page, offset]
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        items = []
        for r in rows:
            d = dict(r)
            try:
                d['images'] = json.loads(d.get('images_json') or '[]')
            except Exception:
                d['images'] = []
            del d['images_json']
            # Serialize datetime
            for k in ('posted_at', 'scraped_at'):
                if d.get(k):
                    d[k] = d[k].strftime('%d/%m/%Y')
            items.append(d)

        return jsonify({'items': items, 'total': total, 'page': page, 'per_page': per_page})
    except Exception as e:
        return jsonify({'error': str(e), 'items': [], 'total': 0}), 500


@app.route('/re/listing/<int:listing_id>')
def re_listing_detail(listing_id):
    """Chi tiết 1 tin — dùng cho modal trên dashboard (không cần mở trang ngoài)."""
    conn = _re_get_conn()
    if not conn:
        return jsonify({'error': 'Không kết nối được DB'}), 500
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, source, external_id, listing_tier, title, description,
                      price, price_text, price_per_m2, area,
                      address, ward, district, city,
                      listing_type, category,
                      bedrooms, bathrooms, floor, total_floors,
                      direction, balcony_dir, legal, furniture,
                      project_name, developer,
                      contact_name, contact_phone,
                      images_json, source_url, posted_at, expires_at, scraped_at, updated_at
               FROM re_listings WHERE id = %s AND COALESCE(is_active, true) = true""",
            (listing_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return jsonify({'error': 'Không tìm thấy tin'}), 404
        d = dict(row)
        try:
            d['images'] = json.loads(d.get('images_json') or '[]')
        except Exception:
            d['images'] = []
        del d['images_json']
        for k in ('posted_at', 'expires_at', 'scraped_at', 'updated_at'):
            if d.get(k):
                d[k] = d[k].strftime('%d/%m/%Y %H:%M') if k in ('scraped_at', 'updated_at') else d[k].strftime('%d/%m/%Y')
        return jsonify(d)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/re/stats')
def re_stats():
    conn = _re_get_conn()
    if not conn:
        return jsonify({'error': 'Không kết nối được DB'}), 500
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*)                                        AS total,
                COUNT(*) FILTER (WHERE city = 'HCM')           AS hcm,
                COUNT(*) FILTER (WHERE city = 'HN')            AS hn,
                COUNT(*) FILTER (WHERE listing_type = 'ban')   AS ban,
                COUNT(*) FILTER (WHERE listing_type = 'thue')  AS thue,
                ROUND(AVG(price_per_m2)/1000000, 1)            AS avg_price_m2_trieu
            FROM re_listings WHERE COALESCE(is_active, true) = true
        """)
        row = dict(cur.fetchone())
        cur.close()
        conn.close()
        return jsonify(row)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    display_name = (data.get("display_name") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email và mật khẩu không được để trống"}), 400
    if len(password) < 6:
        return jsonify({"error": "Mật khẩu phải có ít nhất 6 ký tự"}), 400

    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Email đã được sử dụng"}), 409

        password_hash = generate_password_hash(password)
        cur.execute(
            "INSERT INTO users (email, password_hash, display_name) VALUES (%s, %s, %s) RETURNING id, email, display_name",
            (email, password_hash, display_name or email.split("@")[0])
        )
        user = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        token = create_access_token(identity=str(user["id"]))
        return jsonify({
            "token": token,
            "user": {"id": user["id"], "email": user["email"], "display_name": user["display_name"]}
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email và mật khẩu không được để trống"}), 400

    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, email, password_hash, display_name FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if not user:
            return jsonify({"error": "Email hoặc mật khẩu không đúng"}), 401
        if not user["password_hash"]:
            return jsonify({"error": "Tài khoản này đăng nhập bằng Google. Vui lòng dùng nút 'Đăng nhập bằng Google'"}), 401
        if not check_password_hash(user["password_hash"], password):
            return jsonify({"error": "Email hoặc mật khẩu không đúng"}), 401

        token = create_access_token(identity=str(user["id"]))
        return jsonify({
            "token": token,
            "user": {"id": user["id"], "email": user["email"], "display_name": user["display_name"]}
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/auth/me", methods=["GET"])
@jwt_required()
def me():
    user_id = get_jwt_identity()
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, email, display_name, created_at FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if not user:
            return jsonify({"error": "Không tìm thấy user"}), 404
        return jsonify(dict(user))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/auth/google")
def auth_google():
    """Redirect sang Google OAuth."""
    redirect_uri = "http://localhost:5000/auth/google/callback"
    return google_oauth.authorize_redirect(redirect_uri, prompt="select_account")


@app.route("/auth/google/callback")
def auth_google_callback():
    """Google redirect về đây sau khi user xác nhận."""
    try:
        token = google_oauth.authorize_access_token()
        user_info = token.get("userinfo") or google_oauth.userinfo()

        email        = user_info["email"]
        google_id    = user_info["sub"]
        display_name = user_info.get("name", email.split("@")[0])
        avatar_url   = user_info.get("picture", "")

        conn = _get_db()
        cur  = conn.cursor()

        cur.execute("SELECT id, email, display_name FROM users WHERE email = %s", (email,))
        user = cur.fetchone()

        if user:
            cur.execute(
                "UPDATE users SET google_id = %s, avatar_url = %s WHERE id = %s",
                (google_id, avatar_url, user["id"])
            )
        else:
            cur.execute(
                "INSERT INTO users (email, display_name, avatar_url, google_id) VALUES (%s, %s, %s, %s) RETURNING id, email, display_name",
                (email, display_name, avatar_url, google_id)
            )
            user = cur.fetchone()

        conn.commit()
        cur.close()
        conn.close()

        jwt_token = create_access_token(identity=str(user["id"]))

        from flask import redirect
        frontend_url = f"http://localhost:5000/?token={jwt_token}&name={user['display_name']}&email={user['email']}"
        return redirect(frontend_url)

    except Exception as e:
        from flask import redirect
        import urllib.parse
        safe_error = urllib.parse.quote(str(e).replace('\n', ' '))
        return redirect(f"http://localhost:5000/?auth_error={safe_error}")


@app.route("/chat", methods=["POST"])
def chat_endpoint():
    from langchain_core.messages import HumanMessage
    from chatbot.agent import graph

    user_id = None
    try:
        verify_jwt_in_request(optional=True)
        user_id = get_jwt_identity()
    except Exception:
        pass

    thread_id = f"user_{user_id}" if user_id else "anonymous"

    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "Thiếu trường 'message'"}), 400

    config = {
        "configurable":    {"thread_id": thread_id},
        "recursion_limit": 10,
    }
    messages = [HumanMessage(content=user_message)]

    _TOOL_STATUS = {
        "search_bds":    "Đang tìm kiếm bất động sản trong database...",
        "get_market":    "Đang lấy dữ liệu thị trường chứng khoán...",
        "get_commodity": "Đang lấy giá vàng và xăng dầu...",
        "search_news":   "Đang tìm kiếm tin tức liên quan...",
        "get_weather":    "Đang lấy dữ liệu thời tiết...",
        "get_prediction": "Đang chạy mô hình dự đoán ML...",
    }

    def generate():
        try:
            for chunk, metadata in graph.stream(
                {"messages": messages, "reflection_done": False, "summary": None},
                config,
                stream_mode="messages",
            ):
                node    = metadata.get("langgraph_node")
                content = getattr(chunk, "content", "")

                tool_calls = getattr(chunk, "tool_calls", [])
                if node == "llm" and tool_calls:
                    for tc in tool_calls:
                        name   = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                        status = _TOOL_STATUS.get(name, "Đang xử lý...")
                        yield f"data: {_json.dumps({'status': status})}\n\n"

                if node == "llm" and content:
                    yield f"data: {_json.dumps({'token': content})}\n\n"

            yield f"data: {_json.dumps({'done': True})}\n\n"

        except Exception as e:
            yield f"data: {_json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",  
        },
    )


@app.route('/')
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'index.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), filename)


_weather_cache = {}  
_WEATHER_TTL   = 600 

@app.route("/weather-proxy")
def weather_proxy():
    """
    Proxy thời tiết với server-side cache 10 phút.
    Tránh frontend + chatbot cùng gọi Open-Meteo → 429.
    """
    import time as _time
    city = request.args.get("city", "")
    lat  = request.args.get("lat", "")
    lon  = request.args.get("lon", "")
    days = int(request.args.get("days", 4))

    if not lat or not lon:
        return jsonify({"error": "Thiếu lat/lon"}), 400

    cache_key = f"{lat},{lon},{days}"
    if cache_key in _weather_cache:
        ts, data = _weather_cache[cache_key]
        if _time.time() - ts < _WEATHER_TTL:
            return jsonify(data)

    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,weathercode,windspeed_10m,winddirection_10m"
            f"&hourly=temperature_2m,precipitation_probability,relative_humidity_2m,windspeed_10m,weathercode"
            f"&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,windspeed_10m_max"
            f"&timezone=Asia%2FHo_Chi_Minh&forecast_days={days}"
        )
        resp = requests.get(url, timeout=10)
        if resp.status_code == 429:
            if cache_key in _weather_cache:
                return jsonify(_weather_cache[cache_key][1])
            return jsonify({"error": "API thời tiết đang bận"}), 429
        data = resp.json()
        _weather_cache[cache_key] = (_time.time(), data)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/alerts/geojson")
def alerts_geojson():
    """GeoJSON điểm theo tỉnh: weather + news (từ khóa rủi ro)."""
    with _alerts_state["lock"]:
        g = _alerts_state["geojson"]
    if not g:
        return jsonify(
            {
                "type": "FeatureCollection",
                "features": [],
                "meta": {"generated_at": None, "warming": True},
            }
        )
    return jsonify(g)


if __name__ == "__main__":
    print("=== Vietnam Monitor - Real-Time Streaming ===")
    _init_users_table()
    threading.Thread(target=scraper_loop, daemon=True).start()
    threading.Thread(target=market_loop, daemon=True).start()
    threading.Thread(target=_gold_prediction_loop, daemon=True).start()

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "real_estate"))
        from scrapers import start_scheduler as _start_re_scheduler
        _start_re_scheduler(interval_minutes=360)
        print("[RE] Scheduler BĐS đã khởi động (mỗi 6 giờ)")
    except Exception as _e:
        print(f"[RE] Không thể khởi động scheduler BĐS: {_e}")

    def _embed_loop():
        time.sleep(5 * 60)  
        while True:
            try:
                from chatbot.setup_vectors import embed_listings
                embed_listings()
            except Exception as _e:
                print(f"[EMBED] Lỗi embed listings: {_e}")
            time.sleep(20 * 60)
    threading.Thread(target=_embed_loop, daemon=True, name="embed-loop").start()
    print("[EMBED] Embed loop đã khởi động (mỗi 20 phút)")

    threading.Thread(target=_alerts_rebuild_loop, daemon=True).start()
    print("[ALERTS] Luồng cảnh báo rủi ro đã khởi động (lần đầu sau ~5s, sau đó mỗi 45 phút)")

    def _preload_embeddings():
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
            emb = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
            emb.embed_query("warm up")
            print("[EMBED] Embedding model đã preload xong")
        except Exception as e:
            print(f"[EMBED] Preload lỗi: {e}")
    threading.Thread(target=_preload_embeddings, daemon=True, name="preload-emb").start()

    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)