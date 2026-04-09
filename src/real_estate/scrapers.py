import re, json, time, random, logging, threading
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

try:
    from playwright_stealth import stealth_sync
    _STEALTH_OK = True
except ImportError:
    _STEALTH_OK = False

from db import get_conn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9",
}

CRAWL_SINCE_DAYS = 7

def clear_db():
    """Xoá toàn bộ data và reset sequence ID"""
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("TRUNCATE TABLE re_listings RESTART IDENTITY;")
    conn.commit()
    cur.close()
    conn.close()
    log.info("[DB] Đã xoá toàn bộ data và reset ID")


def _save(rows):
    """Upsert danh sách listings vào DB"""
    if not rows:
        return
    try:
        conn = get_conn()
    except Exception as e:
        log.error(f"[DB] Không kết nối được DB: {e}")
        return

    cur   = conn.cursor()
    saved = 0

    for r in rows:
        if not r.get("source_url"):
            continue
        try:
            cur.execute(
                """
                INSERT INTO re_listings (
                    source, external_id, listing_tier, title, description,
                    price, price_text, price_per_m2, area,
                    address, ward, district, city,
                    listing_type, category,
                    bedrooms, bathrooms, floor, total_floors,
                    direction, balcony_dir, legal, furniture,
                    project_name, developer,
                    contact_name, contact_phone,
                    images_json, source_url,
                    posted_at, expires_at
                ) VALUES (
                    %(source)s, %(external_id)s, %(listing_tier)s, %(title)s, %(description)s,
                    %(price)s, %(price_text)s, %(price_per_m2)s, %(area)s,
                    %(address)s, %(ward)s, %(district)s, %(city)s,
                    %(listing_type)s, %(category)s,
                    %(bedrooms)s, %(bathrooms)s, %(floor)s, %(total_floors)s,
                    %(direction)s, %(balcony_dir)s, %(legal)s, %(furniture)s,
                    %(project_name)s, %(developer)s,
                    %(contact_name)s, %(contact_phone)s,
                    %(images_json)s, %(source_url)s,
                    %(posted_at)s, %(expires_at)s
                )
                ON CONFLICT (source_url) DO UPDATE SET
                    price        = EXCLUDED.price,
                    price_text   = EXCLUDED.price_text,
                    description  = EXCLUDED.description,
                    bedrooms     = EXCLUDED.bedrooms,
                    bathrooms    = EXCLUDED.bathrooms,
                    direction    = EXCLUDED.direction,
                    legal        = EXCLUDED.legal,
                    furniture    = EXCLUDED.furniture,
                    project_name = EXCLUDED.project_name,
                    contact_name = EXCLUDED.contact_name,
                    contact_phone= EXCLUDED.contact_phone,
                    images_json  = EXCLUDED.images_json,
                    is_active    = TRUE,
                    updated_at   = NOW()
                """,
                r,
            )
            saved += 1
        except Exception as e:
            log.error(f"[DB] INSERT lỗi: {e} | url={r.get('source_url', '')[:80]}")
            conn.rollback()

    conn.commit()
    cur.close()
    conn.close()
    log.info(f"[DB] Saved/updated {saved}/{len(rows)} rows")


def _url_exists(source_url):
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("SELECT 1 FROM re_listings WHERE source_url = %s", (source_url,))
        exists = cur.fetchone() is not None
        cur.close()
        conn.close()
        return exists
    except Exception:
        return False


def _all_exist(urls):
    urls = [u for u in urls if u]
    if not urls:
        return False
    try:
        conn  = get_conn()
        cur   = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM re_listings WHERE source_url = ANY(%s)", (urls,))
        cnt   = cur.fetchone()["cnt"]
        cur.close()
        conn.close()
        return cnt >= len(urls)
    except Exception:
        return False

def _parse_price(text):
    if not text:
        return None, text
    t = text.lower().strip()
    try:
        if "tỷ" in t:
            num = float(re.sub(r"[^\d,\.]", "", t).replace(",", "."))
            return int(num * 1_000_000_000), text
        if "triệu" in t:
            num = float(re.sub(r"[^\d,\.]", "", t).replace(",", "."))
            return int(num * 1_000_000), text
    except Exception:
        pass
    return None, text


def _parse_area(text):
    if not text:
        return None
    try:
        return float(re.sub(r"[^\d,\.]", "", text).replace(",", "."))
    except Exception:
        return None


def _parse_int(text):
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def _parse_date(text):
    if not text:
        return None
    t = text.strip().lower()
    try:
        if "hôm nay" in t:
            return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if "hôm qua" in t:
            return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
        if m:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        m = re.search(r"(\d{1,2})/(\d{1,2})", text)
        if m:
            return datetime(datetime.now().year, int(m.group(2)), int(m.group(1)))
    except Exception:
        pass
    return None


def _is_old(posted_at):
    if not posted_at:
        return False
    return posted_at < datetime.now() - timedelta(days=CRAWL_SINCE_DAYS)

def _new_page(pw):
    """Tạo browser page mới với stealth mode"""
    browser = pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    ctx = browser.new_context(
        user_agent=HEADERS["User-Agent"],
        locale="vi-VN",
        viewport={"width": 1440, "height": 900},
    )
    ctx.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins',   {get: () => [1,2,3]});
        Object.defineProperty(navigator, 'languages', {get: () => ['vi-VN','vi','en-US','en']});
        window.chrome = {runtime: {}};
    """)
    page = ctx.new_page()
    if _STEALTH_OK:
        stealth_sync(page)
    return browser, page


def _goto_safe(page, url, timeout=30000):
    """Mở URL và chờ qua Cloudflare challenge nếu có"""
    try:
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    except Exception:
        return  
    for _ in range(10):  
        title = page.title()
        if any(k in title.lower() for k in ["chờ", "checking", "just a moment", "moment"]):
            time.sleep(1)
        else:
            break
    time.sleep(random.uniform(1.5, 2.5))


BDS_SEARCH_URLS = [
    ("https://batdongsan.com.vn/ban-can-ho-chung-cu-tp-hcm", "HCM", "ban", "canho"),
    ("https://batdongsan.com.vn/ban-can-ho-chung-cu-ha-noi", "HN",  "ban", "canho"),
    ("https://batdongsan.com.vn/ban-nha-dat-tp-hcm",         "HCM", "ban", "nha"),
    ("https://batdongsan.com.vn/ban-nha-dat-ha-noi",         "HN",  "ban", "nha"),
    ("https://batdongsan.com.vn/cho-thue-can-ho-chung-cu-tp-hcm", "HCM", "thue", "canho"),
    ("https://batdongsan.com.vn/cho-thue-can-ho-chung-cu-ha-noi", "HN",  "thue", "canho"),
    ("https://batdongsan.com.vn/ban-dat-tp-hcm",             "HCM", "ban", "dat"),
    ("https://batdongsan.com.vn/ban-dat-ha-noi",             "HN",  "ban", "dat"),
]


def _bds_collect_urls(pw, base_url, max_pages=3):
    """Phase 1: Thu thập danh sách URLs từ trang listing"""
    results = []
    for p in range(1, max_pages + 1):
        url = base_url if p == 1 else f"{base_url}/p{p}"
        browser, page = _new_page(pw)
        try:
            _goto_safe(page, url)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            time.sleep(1.5)

            cards = page.query_selector_all(".js__card")
            if not cards:
                log.info(f"[BDS] Không có card ở {url}")
                break

            page_urls = []
            for card in cards:
                try:
                    link_el = card.query_selector("a.js__card-title, a[href*='/pr'], a[href*='-pr']")
                    if not link_el:
                        continue
                    href = link_el.get_attribute("href") or ""
                    link = ("https://batdongsan.com.vn" + href) if not href.startswith("http") else href
                    if link:
                        page_urls.append(link)
                except Exception:
                    pass

            log.info(f"[BDS] Trang {p}: thu thập được {len(page_urls)} URLs")
            results.extend(page_urls)

            if _all_exist(page_urls):
                log.info(f"[BDS] Tất cả URLs trang {p} đã có trong DB → dừng")
                break

        except Exception as e:
            log.warning(f"[BDS] Lỗi thu thập URLs: {e}")
        finally:
            browser.close()

        time.sleep(random.uniform(5, 10))

    return list(dict.fromkeys(results))  

def _interleave_by_city(items):
    """Xen kẽ HCM / HN để Phase 2 không chỉ crawl hết slot cho 1 thành phố."""
    hcm   = [i for i in items if i[1] == "HCM"]
    hn    = [i for i in items if i[1] == "HN"]
    other = [i for i in items if i[1] not in ("HCM", "HN")]
    out   = []
    i = j = 0
    while i < len(hcm) or j < len(hn):
        if i < len(hcm):
            out.append(hcm[i])
            i += 1
        if j < len(hn):
            out.append(hn[j])
            j += 1
    return out + other


def _extract_phone_from_text(text):
    """Lấy SĐT VN từ mô tả nếu người đăng ghi rõ (09x / 03x…)."""
    if not text:
        return ""
    t = text.replace("\u00a0", " ")
    for m in re.finditer(r"0\d{2}[\s.\-]?\d{3}[\s.\-]?\d{3}[\s.\-]?\d{0,4}", t):
        raw = re.sub(r"\D", "", m.group())
        if len(raw) >= 10 and raw.startswith("0"):
            return raw[:10] if len(raw) == 10 else raw[:11]
    return ""


def _bds_parse_detail(page, url, city, listing_type, category):
    """Phase 2: Parse đầy đủ thông tin từ trang chi tiết"""
    try:
        _goto_safe(page, url)
        page.evaluate("window.scrollTo(0, 400)")
        time.sleep(1)

        title_el = page.query_selector("h1.re__pr-title, h1")
        title    = title_el.inner_text().strip() if title_el else ""

        info_items = {}
        for el in page.query_selector_all(".re__pr-short-info-item"):
            parts = [p.strip() for p in el.inner_text().strip().split("\n") if p.strip()]
            if len(parts) >= 2:
                info_items[parts[0].lower()] = parts[1:]

        price_txt    = ""
        price_m2_txt = ""
        area_txt     = ""
        date_txt     = ""
        listing_tier = ""

        for key, vals in info_items.items():
            if "giá" in key:
                price_txt    = vals[0] if vals else ""
                price_m2_txt = vals[1] if len(vals) > 1 else ""
            elif "diện tích" in key:
                area_txt = vals[0] if vals else ""
            elif "ngày đăng" in key:
                date_txt = vals[0] if vals else ""
            elif "loại tin" in key:
                listing_tier = vals[0] if vals else ""

        addr_el = page.query_selector(".re__address-line-1, .re__ldp-address")
        address = addr_el.inner_text().strip().split("\n")[0] if addr_el else ""
        specs = {}
        for el in page.query_selector_all(".re__pr-specs-content-item"):
            parts = [p.strip() for p in el.inner_text().strip().split("\n") if p.strip()]
            if len(parts) >= 2:
                specs[parts[0].lower()] = parts[1]

        direction   = specs.get("hướng nhà", specs.get("hướng", ""))
        balcony_dir = specs.get("hướng ban công", "")
        legal       = specs.get("pháp lý", "")
        furniture   = specs.get("nội thất", "")
        bedrooms    = _parse_int(specs.get("số phòng ngủ", specs.get("phòng ngủ", "")))
        bathrooms   = _parse_int(specs.get("số toilet", specs.get("toilet", specs.get("phòng tắm", ""))))
        floor       = _parse_int(specs.get("tầng số", specs.get("tầng", "")))
        area_spec   = specs.get("diện tích", specs.get("diện tích sử dụng", ""))
        if area_spec and not area_txt:
            area_txt = area_spec

        if not bedrooms and title:
            m_bed = re.search(r"(\d+)\s*(?:phòng ngủ|pn|ngủ|bedroom)", title.lower())
            if m_bed:
                bedrooms = int(m_bed.group(1))

        project_el   = page.query_selector(".re__project-title a, .re__project-name")
        project_name = project_el.inner_text().strip() if project_el else ""
        developer_el = page.query_selector(".re__project-developer")
        developer    = developer_el.inner_text().strip() if developer_el else ""

        desc_el     = page.query_selector(".re__section-body.re__detail-content, .re__pr-description")
        description = desc_el.inner_text().strip() if desc_el else ""

        contact_el   = page.query_selector(".re__contact-name, .js__agent-contact-name")
        contact_name = contact_el.inner_text().strip() if contact_el else ""

        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.35)")
            time.sleep(0.5)
            for sel in ("text=Hiện số", "text=hiện số", "[class*='show-phone']"):
                try:
                    page.locator(sel).first.click(timeout=2500)
                    time.sleep(2.2)
                    break
                except Exception:
                    continue
        except Exception:
            pass

        phone_el = page.query_selector(
            ".re__contact-phone, .re__phone, [data-phone], [data-contact-phone]"
        )
        contact_phone = phone_el.inner_text().strip() if phone_el else ""
        if phone_el:
            for attr in ("data-phone", "data-contact-phone", "data-mobile"):
                v = phone_el.get_attribute(attr)
                if v and re.search(r"\d{9,}", v) and "***" not in v:
                    contact_phone = v.strip()
                    break

        if (not contact_phone or "***" in contact_phone) and description:
            ph = _extract_phone_from_text(description)
            if ph:
                contact_phone = ph

        posted_at = _parse_date(date_txt)

        m      = re.search(r"pr(\d+)", url)
        ext_id = m.group(1) if m else ""

        img_els  = page.query_selector_all(".re__pr-media img, .swiper-slide img")
        img_urls = []
        for img in img_els:
            src = img.get_attribute("src") or img.get_attribute("data-src") or ""
            if src and src.startswith("http") and src not in img_urls:
                img_urls.append(src)

        price, _ = _parse_price(price_txt)
        area     = _parse_area(area_txt)
        price_m2 = None
        if price and area and area > 0:
            price_m2 = int(price / area)
        elif price_m2_txt:
            m_pm2 = re.search(r"[\d.,]+", price_m2_txt)
            if m_pm2:
                try:
                    price_m2 = int(float(m_pm2.group().replace(",", ".")) * 1_000_000)
                except Exception:
                    pass

        district = ""
        ward     = ""
        if address:
            parts = [p.strip() for p in address.split(",")]
            for part in parts:
                pl = part.lower()
                if "quận" in pl or "huyện" in pl:
                    district = part
                elif "phường" in pl or "xã" in pl or "thị trấn" in pl:
                    ward = part

        return {
            "source":        "batdongsan",
            "external_id":   ext_id,
            "listing_tier":  listing_tier,
            "title":         title,
            "description":   description[:2000] if description else None,
            "price":         price,
            "price_text":    price_txt,
            "price_per_m2":  price_m2,
            "area":          area,
            "address":       address,
            "ward":          ward,
            "district":      district,
            "city":          city,
            "listing_type":  listing_type,
            "category":      category,
            "bedrooms":      bedrooms,
            "bathrooms":     bathrooms,
            "floor":         floor,
            "total_floors":  None,
            "direction":     direction,
            "balcony_dir":   balcony_dir,
            "legal":         legal,
            "furniture":     furniture,
            "project_name":  project_name,
            "developer":     developer,
            "contact_name":  contact_name,
            "contact_phone": contact_phone,
            "images_json":   json.dumps(img_urls[:10]),
            "source_url":    url,
            "posted_at":     posted_at,
            "expires_at":    None,
        }

    except Exception as e:
        log.error(f"[BDS] Parse detail lỗi {url}: {e}")
        return None


def scrape_batdongsan(max_pages=3, max_detail=30):
    """
    Phase 1: Thu thập URLs từ trang danh sách
    Phase 2: Vào từng trang chi tiết lấy đầy đủ thông tin
    """
    log.info("[BDS] === Phase 1: Thu thập URLs ===")
    all_items = []  

    with sync_playwright() as pw:
        for base_url, city, listing_type, category in BDS_SEARCH_URLS:
            urls = _bds_collect_urls(pw, base_url, max_pages)
            for u in urls:
                all_items.append((u, city, listing_type, category))
            log.info(f"[BDS] {base_url} → {len(urls)} URLs")

    all_items = _interleave_by_city(all_items)
    log.info(f"[BDS] Tổng: {len(all_items)} URLs (đã xen kẽ HCM/HN). Bắt đầu Phase 2...")

    items_to_scrape = [i for i in all_items if not _url_exists(i[0])]
    items_to_scrape = items_to_scrape[:max_detail]

    log.info(f"[BDS] === Phase 2: Crawl {len(items_to_scrape)} trang chi tiết ===")

    with sync_playwright() as pw:
        for idx, (url, city, listing_type, category) in enumerate(items_to_scrape):
            browser, page = _new_page(pw)
            try:
                row = _bds_parse_detail(page, url, city, listing_type, category)
                if row:
                    _save([row])
                    log.info(f"[BDS] [{idx+1}/{len(items_to_scrape)}] ✓ {row['title'][:50]}")
            except Exception as e:
                log.error(f"[BDS] Detail page lỗi: {e}")
            finally:
                browser.close()

            time.sleep(random.uniform(3, 6))

    log.info("[BDS] Xong")


MOGI_URLS = [
    ("https://mogi.vn/thue-can-ho-chung-cu/tp-hcm", "HCM", "thue", "canho"),
    ("https://mogi.vn/thue-can-ho-chung-cu/ha-noi",  "HN",  "thue", "canho"),
    ("https://mogi.vn/ban-can-ho-chung-cu/tp-hcm",   "HCM", "ban",  "canho"),
    ("https://mogi.vn/ban-can-ho-chung-cu/ha-noi",   "HN",  "ban",  "canho"),
    ("https://mogi.vn/ban-nha/tp-hcm",               "HCM", "ban",  "nha"),
    ("https://mogi.vn/ban-nha/ha-noi",               "HN",  "ban",  "nha"),
    ("https://mogi.vn/ban-dat/tp-hcm",               "HCM", "ban",  "dat"),
    ("https://mogi.vn/ban-dat/ha-noi",               "HN",  "ban",  "dat"),
]


def _get(url, retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r
        except Exception as e:
            log.warning(f"Retry {i+1} — {url} — {e}")
        time.sleep(random.uniform(2, 4))
    return None


def scrape_mogi(max_pages=3):
    all_rows = []

    for base_url, city, listing_type, category in MOGI_URLS:
        for p in range(1, max_pages + 1):
            url = base_url if p == 1 else f"{base_url}?paged={p}"
            log.info(f"[MOGI] {url}")
            r = _get(url)
            if not r:
                break

            soup           = BeautifulSoup(r.text, "lxml")
            cards          = soup.select(".prop-item")
            rows_this_page = []

            for card in cards:
                try:
                    title_el  = card.select_one(".prop-title a")
                    title     = title_el.get_text(strip=True) if title_el else ""
                    link      = title_el["href"] if title_el else ""
                    if link and not link.startswith("http"):
                        link = "https://mogi.vn" + link

                    price_el  = card.select_one(".price")
                    price_txt = price_el.get_text(strip=True) if price_el else ""
                    area_el   = card.select_one(".info-item.square, .area")
                    area_txt  = area_el.get_text(strip=True) if area_el else ""
                    addr_el   = card.select_one(".address")
                    address   = addr_el.get_text(strip=True) if addr_el else ""
                    date_el   = card.select_one(".time, .date")
                    date_txt  = date_el.get_text(strip=True) if date_el else ""
                    bed_el    = card.select_one(".bedroom, .info-item.bedroom")
                    bed_txt   = bed_el.get_text(strip=True) if bed_el else ""
                    imgs      = []
                    for img in card.select("img"):
                        src = img.get("src") or img.get("data-src") or ""
                        if src and src.startswith("http"):
                            imgs.append(src)

                    price, _  = _parse_price(price_txt)
                    area      = _parse_area(area_txt)
                    posted_at = _parse_date(date_txt)
                    bedrooms  = _parse_int(bed_txt)
                    ext_id    = re.search(r"(\d+)", link or "")
                    ext_id    = ext_id.group(1) if ext_id else ""

                    price_m2  = int(price / area) if price and area and area > 0 else None

                    if not link:
                        continue

                    rows_this_page.append({
                        "source":        "mogi",
                        "external_id":   ext_id,
                        "listing_tier":  None,
                        "title":         title,
                        "description":   None,
                        "price":         price,
                        "price_text":    price_txt,
                        "price_per_m2":  price_m2,
                        "area":          area,
                        "address":       address,
                        "ward":          None,
                        "district":      None,
                        "city":          city,
                        "listing_type":  listing_type,
                        "category":      category,
                        "bedrooms":      bedrooms,
                        "bathrooms":     None,
                        "floor":         None,
                        "total_floors":  None,
                        "direction":     None,
                        "balcony_dir":   None,
                        "legal":         None,
                        "furniture":     None,
                        "project_name":  None,
                        "developer":     None,
                        "contact_name":  None,
                        "contact_phone": None,
                        "images_json":   json.dumps(imgs[:5]),
                        "source_url":    link,
                        "posted_at":     posted_at,
                        "expires_at":    None,
                    })
                except Exception as e:
                    log.warning(f"[MOGI] Parse card lỗi: {e}")

            if not rows_this_page:
                break

            page_urls = [r["source_url"] for r in rows_this_page]
            if _all_exist(page_urls):
                log.info(f"[MOGI] Tất cả tin trang {p} đã có trong DB → dừng")
                break

            fresh = [r for r in rows_this_page if not _is_old(r["posted_at"])]
            if fresh:
                _save(fresh)
                all_rows.extend(fresh)
                log.info(f"[MOGI] Trang {p}: {len(fresh)} tin mới")

            if len(fresh) < len(rows_this_page):
                log.info(f"[MOGI] Gặp tin cũ → dừng")
                break

            time.sleep(random.uniform(2, 4))

    return all_rows



_scheduler_started = False
_scheduler_lock    = threading.Lock()


def run_all(max_pages=3, max_detail=60):
    log.info("=== START SCRAPING ===")

    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM re_listings")
        cnt  = cur.fetchone()["cnt"]
        cur.close()
        conn.close()
        log.info(f"[DB] Kết nối OK — re_listings hiện có {cnt} rows")
    except Exception as e:
        log.error(f"[DB] Kết nối THẤT BẠI: {e}")
        return

    try:
        scrape_batdongsan(max_pages, max_detail)
    except Exception as e:
        log.error(f"[BDS] scraper crashed: {e}")
        import traceback; traceback.print_exc()

    try:
        scrape_mogi(max_pages)
    except Exception as e:
        log.error(f"[MOGI] scraper crashed: {e}")
        import traceback; traceback.print_exc()

    log.info("=== DONE ===")


def start_scheduler(interval_minutes=15):
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    def _loop():
        log.info(f"[SCHEDULER] Khởi động — interval {interval_minutes} phút")
        while True:
            try:
                run_all(max_pages=3, max_detail=60)
            except Exception as e:
                log.error(f"[SCHEDULER] Lỗi: {e}")
            time.sleep(interval_minutes * 60)

    t = threading.Thread(target=_loop, daemon=True, name="re-scheduler")
    t.start()


if __name__ == "__main__":
    clear_db()
    run_all(max_pages=3, max_detail=60)
