# Vietnam Monitor

Dashboard tổng hợp thông tin thị trường Việt Nam theo thời gian thực, tích hợp chatbot AI, dự đoán Machine Learning và tìm kiếm ngữ nghĩa — xây dựng trên LangGraph, pgvector và GPT-4o-mini.

---

## Tổng quan

Vietnam Monitor thu thập dữ liệu trực tiếp từ 5 lĩnh vực và cho phép người dùng khám phá qua dashboard trực quan và chatbot AI:

- Tin tức thời gian thực, hiển thị theo địa lý trên bản đồ 63 tỉnh/thành
- Dự báo thời tiết  cho từng tỉnh/thành
- Chỉ số chứng khoán (VNINDEX, VN30, HNX, UPCOM) và tra cứu mã cổ phiếu
- Giá vàng (SJC, DOJI) và xăng dầu (RON95, E5, diesel) cập nhật real-time
- Tìm kiếm bất động sản bằng vector similarity
- Dự đoán ML xu hướng cổ phiếu, giá vàng, và chiều hướng giá xăng
- Chatbot AI trả lời câu hỏi đa lĩnh vực cùng lúc

---

## Kiến trúc AI & ML

### 1. Chatbot AI Agent — LangGraph + GPT-4o-mini

Chatbot được xây dựng là một **LangGraph agent có trạng thái (stateful)**, không phải chuỗi prompt-response đơn giản.

```
Tin nhắn user
    │
    ├─ [summarize]     nếu history > 10 messages → nén bằng LLM, giữ 6 messages gần nhất
    ├─ [inject_memory] tải sở thích user từ PostgresStore
    ├─ [llm]           GPT-4o-mini quyết định gọi tool nào (parallel_tool_calls=True)
    ├─ [tools]         tất cả tool được chọn chạy đồng thời
    ├─ [llm]           định dạng câu trả lời cuối từ kết quả tool
    └─ [save_memory]   background thread → lưu sở thích user (không chặn response)
```

**Các quyết định thiết kế quan trọng:**

- `parallel_tool_calls=True` — khi user hỏi giá cổ phiếu VÀ dự đoán, cả hai tool chạy trong 1 vòng thay vì 2 LLM call tuần tự, giảm latency xuống một nửa
- **PostgresSaver checkpointing** — toàn bộ lịch sử hội thoại được lưu theo `thread_id`, tồn tại qua các lần restart server
- **Summarization node** — khi history vượt 10 messages, messages cũ được tóm tắt (không bị xóa) để giữ ngữ cảnh trong khi giảm chi phí token
- **Non-blocking memory** — `save_memory` spawn daemon thread và return ngay; user không phải đợi ghi memory

**Caching nhiều tầng** để giảm latency:

| Tầng | Dữ liệu | TTL |
|------|---------|-----|
| `@lru_cache(maxsize=256)` | Embedding vector theo query text | Suốt vòng đời process |
| In-process dict | Chỉ số thị trường / cổ phiếu | 60 giây |
| In-process dict | Giá vàng / xăng dầu | 5 phút |
| Flask endpoint | Weather API proxy | 10 phút |
| Flask endpoint | Dự đoán ML xăng dầu | 30 phút |

Sơ đồ luồng chi tiết: [`docs/langgraph-flow.md`](docs/langgraph-flow.md)

---

### 2. Tìm kiếm Bất động sản — pgvector HNSW

Danh sách BDS được embed và index vào PostgreSQL dùng extension **pgvector** với HNSW index.

**Pipeline tìm kiếm:**
```
Query tự nhiên của user
    │
    ├─ _extract_city()      → SQL filter cứng: city = 'HN' | 'HCM'
    ├─ _extract_district()  → SQL filter cứng: district ILIKE '%Cầu Giấy%'
    ├─ embed_query_cached() → HuggingFace all-MiniLM-L6-v2 (384 chiều, LRU cache)
    └─ pgvector HNSW query
         SET hnsw.ef_search = 60
         WHERE city = %s AND district ILIKE %s
         ORDER BY embedding <=> query_vector
         LIMIT 10
```

**Cấu hình index**: `m=16, ef_construction=64, vector_cosine_ops`

Filter địa lý (city, district) được áp dụng như ràng buộc SQL cứng trước khi vector ranking — semantic search xử lý ngữ cảnh giá, diện tích, số phòng ngủ. Nếu filter district không có kết quả, tự động fallback về chỉ filter city.

---

### 3. Tìm kiếm Tin tức Hybrid — Semantic + Keyword + RRF

Bài báo được embed vào **ChromaDB** và tìm kiếm bằng **Reciprocal Rank Fusion (RRF)**:

```
Query → embed_query_cached() → semantic search (ChromaDB cosine) → semantic rank
Query → tokenize             → keyword scoring (tần suất từ)     → keyword rank

RRF score:  1 / (60 + semantic_rank) + 1 / (60 + keyword_rank)

Kết quả: sắp xếp theo RRF score → top 5 với phân trang
```

**Category filter** (13 danh mục: thể thao, công nghệ, thế giới,...) được truyền như ChromaDB `where` clause. LLM tự suy ra danh mục đúng từ cách đặt câu hỏi của user và truyền vào như tham số.

---

### 4. Dự đoán ML — Gradient Boosting

Ba model riêng biệt dự đoán chiều hướng thị trường dùng scikit-learn:

**Dự đoán cổ phiếu** (`src/ml/train_model_cp.ipynb`):
- Input features: OHLCV 30 ngày từ vnstock — returns, volatility, volume ratio, RSI proxy, moving average crossover
- Models: `GradientBoostingClassifier` (tăng/giảm) + `GradientBoostingRegressor` (biên độ %)
- Output: chiều hướng + % thay đổi + confidence score

**Dự đoán vàng** (`src/ml/train_model_gold.ipynb`):
- Input features: lịch sử giá SJC + tỷ giá XAU/USD (yfinance), rolling statistics, momentum
- Models: `GradientBoostingClassifier` + `GradientBoostingRegressor`
- Output: chiều hướng + giá dự đoán + confidence

**Dự đoán xăng dầu**:
- Input features: giá dầu thô Brent (yfinance), tỷ giá USD/VND, rolling averages
- Model: `GradientBoostingClassifier`
- Output: chiều hướng + confidence + lý do

Tất cả model dùng `StandardScaler` chuẩn hóa features. Artifacts được lưu dạng `.pkl` trong `src/ml/`.

---

### 5. Data Pipeline

`src/process_data.py` vừa là Flask server vừa là lớp điều phối dữ liệu, chạy các vòng lặp nền khi khởi động:

| Vòng lặp | Chu kỳ | Chức năng |
|----------|--------|-----------|
| News scraper | SSE liên tục | Fetch RSS feeds, geocode về tọa độ tỉnh/thành, stream về browser |
| Market loop | 60 giây | Lấy chỉ số chứng khoán VN qua TCBS API |
| BDS scraper | Mỗi 6 giờ | Playwright crawl batdongsan.com.vn với stealth mode |
| Embed loop | Mỗi 20 phút | Tạo pgvector embeddings cho BDS listings mới |
| Alerts loop | Mỗi 45 phút | Rebuild GeoJSON cảnh báo rủi ro từ điểm severity tin tức |

**BDS scraper** dùng Playwright với anti-bot bypass (stealth mode, random delay) để crawl danh sách BDS, parse giá, diện tích, số phòng ngủ, quận, phường từ CSS selectors.

---

## Tech Stack

| Tầng | Công nghệ |
|------|----------|
| Frontend | HTML/CSS/JS (ES6+), Mapbox GL JS — không dùng framework |
| Backend | Python 3.11, Flask, Server-Sent Events (SSE) |
| LLM | OpenAI GPT-4o-mini, LangChain, LangGraph |
| Vector DB (BDS) | PostgreSQL 15 + pgvector (HNSW) |
| Vector DB (Tin tức) | ChromaDB |
| Embedding model | HuggingFace `all-MiniLM-L6-v2` (384 chiều, chạy local) |
| ML | scikit-learn (Gradient Boosting, Random Forest), joblib |
| Nguồn dữ liệu | vnstock, yfinance, Open-Meteo, SJC/DOJI APIs |
| Scraping | Playwright (stealth), BeautifulSoup, feedparser |
| Auth | JWT (flask-jwt-extended) + Google OAuth 2.0 (authlib) |
| Observability | Langfuse self-hosted trên ClickHouse |

---

## Cài đặt

### Yêu cầu

- Python 3.11+
- PostgreSQL 15+ với extension `pgvector`
- OpenAI API key

### Cài đặt

```bash
git clone https://github.com/your-username/vietnam-monitor.git
cd vietnam-monitor

pip install -r requirements.txt
playwright install chromium
```

### PostgreSQL + pgvector

```bash
# macOS
brew install postgresql@15
brew services start postgresql@15

# Ubuntu/Debian
sudo apt install postgresql-15 postgresql-15-pgvector

# Bật extension
psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Cấu hình môi trường

```bash
cp .env.example .env
# Điền OPENAI_API_KEY (bắt buộc) và các key tùy chọn
```

Google OAuth (tùy chọn — cho phép đăng nhập bằng Google):
```bash
cp googles.env.example googles.env
# Điền client_id và client_secret từ Google Cloud Console
# Authorized redirect URI: http://localhost:5000/auth/google/callback
```

### Chạy server

```bash
cd src
python process_data.py
```

Lần đầu khởi động, server tự động:
- Tạo tất cả bảng PostgreSQL (users, BDS listings, LangGraph checkpoints, memory store)
- Fetch tin tức và index vào ChromaDB
- Preload HuggingFace embedding model
- Khởi động Playwright BDS crawler nền

Mở dashboard:
```bash
cd src && python3 -m http.server 8080
# Truy cập: http://localhost:8080
```

---

## Cấu trúc thư mục

```
vietnam-monitor/
├── src/
│   ├── chatbot/
│   │   ├── agent.py           # LangGraph StateGraph, nodes, routing, streaming
│   │   ├── prompts.py         # System prompt với quy tắc gọi tool song song
│   │   ├── setup_vectors.py   # Pipeline embed BDS
│   │   └── tools/
│   │       ├── _embeddings.py # HuggingFace singleton + LRU query cache
│   │       ├── bds.py         # pgvector HNSW + SQL filter city/district
│   │       ├── market.py      # Dữ liệu chứng khoán + cache 60 giây
│   │       ├── commodity.py   # Giá vàng/xăng + cache 5 phút
│   │       ├── news.py        # ChromaDB hybrid search + RRF ranking
│   │       ├── weather.py     # Open-Meteo + cache 10 phút
│   │       └── predict.py     # Gọi ML prediction endpoints
│   ├── ml/
│   │   ├── train_model_cp.ipynb    # Notebook train model cổ phiếu (GBM)
│   │   ├── train_model_gold.ipynb  # Notebook train model vàng (GBM)
│   │   ├── model_clf.pkl           # Classifier cổ phiếu (tăng/giảm)
│   │   ├── model_reg.pkl           # Regressor cổ phiếu (biên độ)
│   │   ├── model_gold_clf.pkl      # Classifier vàng
│   │   ├── model_gold_reg.pkl      # Regressor vàng
│   │   ├── scaler.pkl / scaler_gold.pkl
│   │   └── metadata.json / metadata_gold.json
│   ├── real_estate/
│   │   ├── scrapers.py        # Playwright crawler (stealth, anti-bot)
│   │   ├── db.py              # PostgreSQL BDS operations
│   │   └── api.py             # Flask BDS endpoints
│   ├── process_data.py        # Flask server + tất cả schedulers nền
│   ├── alerts_engine.py       # Tính điểm severity tin tức → GeoJSON rủi ro
│   ├── index.html             # Dashboard chính
│   ├── market.js              # Module UI chứng khoán
│   ├── commodity.js           # Module UI vàng/xăng
│   ├── weather.js             # Module UI thời tiết
│   └── alerts_map.js          # Mapbox overlay cảnh báo rủi ro
├── docs/
│   └── langgraph-flow.md      # Sơ đồ kiến trúc LangGraph chi tiết
├── docker-compose.yml         # Langfuse self-hosted observability
├── requirements.txt
├── .env.example
└── googles.env.example
```

---

## Ví dụ câu hỏi Chatbot

Agent xử lý câu hỏi đa lĩnh vực với parallel tool execution:

```
"thị trường chứng khoán hôm nay và xu hướng ACB tuần tới"
→ get_market("ACB") + get_prediction("ACB")   [song song — 1 LLM round]

"giá vàng và dự đoán xu hướng"
→ get_commodity("gold") + get_prediction("gold")   [song song]

"tôi có 10 tỷ muốn mua nhà ở Cầu Giấy, 2 phòng ngủ"
→ search_bds(query)   [HNSW + city=HN + district ILIKE '%Cầu Giấy%']

"thời tiết Đà Nẵng và tin tức du lịch mới nhất"
→ get_weather("Đà Nẵng") + search_news("du lịch", category="du lịch")   [song song]
```

---

## Retrain ML Models

```bash
cd src/ml
jupyter notebook train_model_cp.ipynb     # cổ phiếu
jupyter notebook train_model_gold.ipynb   # vàng
```

Mỗi notebook tự fetch dữ liệu lịch sử mới, train classifier + regressor, và lưu lại file `.pkl`.

---

## Observability

Langfuse trace mọi LLM call, tool call, token usage và latency:

```bash
docker compose up -d
# Dashboard: http://localhost:3000
```

Điền `LANGFUSE_PUBLIC_KEY` và `LANGFUSE_SECRET_KEY` vào `.env`.

---

## Lưu ý

- Dữ liệu BDS được crawl từ batdongsan.com.vn chỉ phục vụ mục đích nghiên cứu
- Dự đoán ML chỉ mang tính tham khảo, không phải tư vấn đầu tư
- Embedding model chạy local trên CPU (~200ms lần đầu, cache sau đó)
