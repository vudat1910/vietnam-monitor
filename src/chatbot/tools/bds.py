import re
import psycopg2
from psycopg2.extras import RealDictCursor
from langchain_core.tools import tool
from ._embeddings import embed_query_cached

DB_CONFIG = {
    "host":   "127.0.0.1",
    "port":   5432,
    "dbname": "postgres",
    "user":   "postgres",
}

_CITY_MAP = {
    "hà nội": "HN", "ha noi": "HN", "hanoi": "HN",
    "hà noi": "HN", "hn": "HN",
    "hồ chí minh": "HCM", "ho chi minh": "HCM", "hcm": "HCM",
    "sài gòn": "HCM", "saigon": "HCM", "tphcm": "HCM",
}

_HN_DISTRICTS = [
    "thanh xuân", "hoàn kiếm", "đống đa", "hai bà trưng", "ba đình",
    "tây hồ", "cầu giấy", "hoàng mai", "long biên", "hà đông",
    "nam từ liêm", "bắc từ liêm", "thanh trì", "gia lâm",
    "hoài đức", "đan phượng", "đông anh", "sóc sơn", "mê linh",
    "thạch thất", "quốc oai", "thường tín", "phú xuyên",
]
_HCM_DISTRICTS = [
    "quận 1", "quận 2", "quận 3", "quận 4", "quận 5", "quận 6",
    "quận 7", "quận 8", "quận 9", "quận 10", "quận 11", "quận 12",
    "bình thạnh", "phú nhuận", "gò vấp", "tân bình", "tân phú",
    "bình tân", "thủ đức", "bình chánh", "hóc môn", "củ chi",
]

_DISTRICT_TERM_MAP = {
    # Hà Nội
    "cầu giấy":    "Cầu Giấy",
    "hoàng mai":   "Hoàng Mai",
    "đống đa":     "Đống Đa",
    "hai bà trưng":"Hai Bà Trưng",
    "hoàn kiếm":   "Hoàn Kiếm",
    "ba đình":     "Ba Đình",
    "tây hồ":      "Tây Hồ",
    "thanh xuân":  "Thanh Xuân",
    "hà đông":     "Hà Đông",
    "long biên":   "Long Biên",
    "nam từ liêm": "Nam Từ Liêm",
    "bắc từ liêm": "Bắc Từ Liêm",
    "gia lâm":     "Gia Lâm",
    "thanh trì":   "Thanh Trì",
    "hoài đức":    "Hoài Đức",
    "đan phượng":  "Đan Phượng",
    "đông anh":    "Đông Anh",
    "sóc sơn":     "Sóc Sơn",
    "mê linh":     "Mê Linh",
    "thạch thất":  "Thạch Thất",
    "quốc oai":    "Quốc Oai",
    # Hồ Chí Minh
    "quận 1":      "Quận 1",  "q1": "Quận 1",
    "quận 2":      "Quận 2",  "q2": "Quận 2",
    "quận 3":      "Quận 3",  "q3": "Quận 3",
    "quận 4":      "Quận 4",  "q4": "Quận 4",
    "quận 5":      "Quận 5",  "q5": "Quận 5",
    "quận 6":      "Quận 6",  "q6": "Quận 6",
    "quận 7":      "Quận 7",  "q7": "Quận 7",
    "quận 8":      "Quận 8",  "q8": "Quận 8",
    "quận 9":      "Quận 9",  "q9": "Quận 9",
    "quận 10":     "Quận 10", "q10": "Quận 10",
    "quận 11":     "Quận 11", "q11": "Quận 11",
    "quận 12":     "Quận 12", "q12": "Quận 12",
    "bình thạnh":  "Bình Thạnh",
    "phú nhuận":   "Phú Nhuận",
    "gò vấp":      "Gò Vấp",
    "tân bình":    "Tân Bình",
    "tân phú":     "Tân Phú",
    "bình tân":    "Bình Tân",
    "thủ đức":     "Thủ Đức",
    "bình chánh":  "Bình Chánh",
    "hóc môn":     "Hóc Môn",
    "củ chi":      "Củ Chi",
}


def _extract_city(query: str):
    q = query.lower()
    for kw, code in _CITY_MAP.items():
        if kw in q:
            return code
    for d in _HN_DISTRICTS:
        if d in q:
            return "HN"
    for d in _HCM_DISTRICTS:
        if d in q:
            return "HCM"
    return ""


def _extract_district(query: str) -> str:
    """Trích xuất tên quận/huyện từ query → trả về term để ILIKE filter."""
    q = query.lower()
    for kw in sorted(_DISTRICT_TERM_MAP, key=len, reverse=True):
        if kw in q:
            return _DISTRICT_TERM_MAP[kw]
    return ""


def _fmt_price(price: int) -> str:
    if not price:
        return ""
    if price >= 1_000_000_000:
        return f"{price / 1_000_000_000:.1f} tỷ"
    if price >= 1_000_000:
        return f"{price / 1_000_000:.0f} triệu"
    return f"{price:,} VNĐ"


def _price_from_title(title: str) -> str:
    if not title:
        return "Thoả thuận"
    m = re.search(r'([\d][.,\d]*\s*(?:tỷ|triệu)(?:/tháng|/th)?)', title, re.IGNORECASE)
    return m.group(1).strip() if m else "Thoả thuận"


@tool
def search_bds(query: str) -> str:
    """
    Tìm kiếm bất động sản bằng HNSW semantic search (pgvector).
    Dùng khi user hỏi về nhà, căn hộ, đất, mua bán/cho thuê BDS.

    Truyền NGUYÊN VĂN câu hỏi của user làm query để semantic search
    hiểu đúng ngữ cảnh: giá, diện tích, số phòng, địa điểm.
    Ví dụ: 'tôi có 6 tỷ muốn mua căn hộ 2 phòng ngủ 100m2 tại Hà Nội'
    """
    try:
        city_code    = _extract_city(query)
        district_term = _extract_district(query)

        conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
        cur  = conn.cursor()

        cur.execute("SET hnsw.ef_search = 60")

        query_vec = list(embed_query_cached(query))
        vec_str   = "[" + ",".join(map(str, query_vec)) + "]"

        where_parts = ["is_active = TRUE", "embedding IS NOT NULL"]
        params      = [vec_str]

        if city_code:
            where_parts.append("city = %s")
            params.append(city_code)

        if district_term:
            where_parts.append("district ILIKE %s")
            params.append(f"%{district_term}%")

        params.append(vec_str)
        where_sql = " AND ".join(where_parts)

        cur.execute(f"""
            SELECT id, title, price, price_text, area, address,
                   ward, district, city, bedrooms, bathrooms,
                   category, listing_type, source_url,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM re_listings
            WHERE {where_sql}
            ORDER BY embedding <=> %s::vector
            LIMIT 10
        """, params)

        rows = cur.fetchall()

        if not rows and district_term and city_code:
            params_fb = [vec_str, city_code, vec_str]
            cur.execute("""
                SELECT id, title, price, price_text, area, address,
                       ward, district, city, bedrooms, bathrooms,
                       category, listing_type, source_url,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM re_listings
                WHERE is_active = TRUE AND embedding IS NOT NULL AND city = %s
                ORDER BY embedding <=> %s::vector
                LIMIT 10
            """, params_fb)
            rows = cur.fetchall()

        cur.close()
        conn.close()

        if not rows:
            return "Không tìm thấy bất động sản phù hợp."

        location_label = ""
        if district_term and city_code:
            city_name = {"HN": "Hà Nội", "HCM": "Hồ Chí Minh"}.get(city_code, "")
            location_label = f" tại {district_term}, {city_name}"
        elif city_code:
            city_name = {"HN": "Hà Nội", "HCM": "Hồ Chí Minh"}.get(city_code, "")
            location_label = f" tại {city_name}" if city_name else ""

        results = []
        for r in rows[:5]:
            price_str  = r.get("price_text") or _fmt_price(r.get("price") or 0) or _price_from_title(r.get("title", ""))
            sim        = r.get("similarity") or 0
            addr_parts = [p for p in [r.get("district"), r.get("ward"), r.get("city")] if p]
            results.append(
                f"📍 {r['title']}\n"
                f"   Giá: {price_str} | Diện tích: {r.get('area') or '?'}m² | {r.get('bedrooms') or '?'}PN\n"
                f"   Địa chỉ: {', '.join(addr_parts)}\n"
                f"   Loại: {r.get('category','')} ({r.get('listing_type','')}) | Độ phù hợp: {sim:.0%}\n"
                f"   Link: {r.get('source_url','')}"
            )

        return f"Tìm thấy {len(rows)} kết quả{location_label}, top 5 phù hợp nhất:\n\n" + "\n\n".join(results)

    except Exception as e:
        return f"Lỗi tìm kiếm BDS: {str(e)}"
