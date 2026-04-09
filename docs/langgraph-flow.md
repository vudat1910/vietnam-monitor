# LangGraph Flow — Vietnam Monitor Chatbot

## Tổng quan kiến trúc

Chatbot được xây dựng bằng **LangGraph** — framework tạo AI agent có trạng thái (stateful), cho phép vòng lặp LLM → Tool → LLM với checkpointing tự động.

- **LLM**: OpenAI GPT-4o-mini (`parallel_tool_calls=True`)
- **Checkpointing**: PostgresSaver — lưu toàn bộ state theo `thread_id` vào PostgreSQL
- **Long-term memory**: PostgresStore — lưu sở thích user giữa các session
- **Observability**: Langfuse trace mọi LLM call, tool call, token usage

---

## State

```python
class ChatState(TypedDict):
    messages:        list[BaseMessage]  # toàn bộ tin nhắn (Human/AI/Tool)
    summary:         Optional[str]      # tóm tắt messages cũ khi history > 10
    reflection_done: bool               # dự phòng
```

State được persist vào PostgreSQL sau mỗi node. Mỗi user (`thread_id`) có state riêng biệt và không mất khi restart server.

---

## Sơ đồ luồng đầy đủ

```
┌──────────────────────────────────────────────────────────────────┐
│                            START                                 │
│                     (user gửi 1 tin nhắn)                        │
│         state.messages += [HumanMessage(content=...)]            │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │      route_start       │
                    │  len(messages) > 10?   │
                    └────────────┬──────────┘
                                 │
                ┌────────────────┴────────────────┐
           > 10 msgs                          ≤ 10 msgs
                │                                 │
                ▼                                 │
  ┌─────────────────────────┐                    │
  │        summarize        │                    │
  │                         │                    │
  │  Vấn đề: giữ toàn bộ   │                    │
  │  history → LLM nhận     │                    │
  │  nhiều token → chậm,    │                    │
  │  tốn tiền.              │                    │
  │                         │                    │
  │  Giải pháp:             │                    │
  │  - Giữ 6 messages gần   │                    │
  │    nhất nguyên vẹn      │                    │
  │  - Tóm tắt phần còn lại │                    │
  │    thành 3-4 câu bằng   │                    │
  │    GPT-4o-mini           │                    │
  │  - Lưu vào state.summary│                    │
  │                         │                    │
  └────────────┬────────────┘                    │
               │                                 │
               └─────────────────┬───────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │     inject_memory      │
                    │                        │
                    │  Đọc PostgresStore     │
                    │  theo thread_id.       │
                    │                        │
                    │  Nếu có memory cũ:     │
                    │  "user quan tâm BDS    │
                    │   Cầu Giấy, 2PN"       │
                    │  → inject SystemMessage│
                    │    vào đầu context     │
                    │                        │
                    │  Nếu không có:         │
                    │  → return {} ngay      │
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────────────────────────┐
                    │                   llm                      │
                    │                                            │
                    │  Context gửi vào GPT-4o-mini:             │
                    │  ┌──────────────────────────────────────┐  │
                    │  │ [1] System Prompt                    │  │
                    │  │     - Quy tắc 5 chủ đề              │  │
                    │  │     - Rule dự đoán (ưu tiên cao)    │  │
                    │  │     - Quy tắc parallel tool calls   │  │
                    │  ├──────────────────────────────────────┤  │
                    │  │ [2] Long-term memory (nếu có)        │  │
                    │  │     "user thích BDS Hà Nội..."       │  │
                    │  ├──────────────────────────────────────┤  │
                    │  │ [3] Summary hội thoại cũ (nếu có)   │  │
                    │  ├──────────────────────────────────────┤  │
                    │  │ [4] 10 messages gần nhất             │  │
                    │  ├──────────────────────────────────────┤  │
                    │  │ [5] Tool schemas (6 tools):          │  │
                    │  │     get_weather, get_commodity,      │  │
                    │  │     get_market, search_bds,          │  │
                    │  │     search_news, get_prediction      │  │
                    │  └──────────────────────────────────────┘  │
                    │                                            │
                    │  GPT-4o-mini quyết định:                  │
                    │  A. Gọi 1 tool                            │
                    │  B. Gọi nhiều tool CÙNG LÚC (parallel)   │
                    │  C. Trả lời thẳng (không cần tool)       │
                    └─────────────────┬──────────────────────────┘
                                      │
                    ┌─────────────────▼────────────────────┐
                    │           route_after_llm             │
                    │                                       │
                    │  Kiểm tra last message:               │
                    │  - Có tool_calls? → tools             │
                    │  - Không có tool_calls:               │
                    │      topic in-scope → save_memory     │
                    │      topic out-of-scope → __end__     │
                    └──┬────────────────────────┬───────────┘
                       │                        │
               có tool_calls              không có tool_calls
                       │                        │
                       ▼                ┌───────┴──────┐
          ┌─────────────────────┐   in-scope       out-of-scope
          │        tools        │  (5 chủ đề)    (chào hỏi,...)
          │  (ToolNode)         │       │               │
          │                     │       │               ▼
          │  Parallel execution:│       │          ┌─────────┐
          │  Tất cả tool_calls  │       │          │ __end__ │
          │  chạy đồng thời     │       │          │ Không   │
          │  trong 1 round:     │       │          │ lưu     │
          │                     │       │          │ memory  │
          │  get_weather        │       │          └─────────┘
          │  → Open-Meteo API   │       │
          │    (cache 10 phút)  │       │
          │                     │       │
          │  get_commodity      │       │
          │  → Flask /gold      │       │
          │    /fuel endpoints  │       │
          │    (cache 5 phút)   │       │
          │                     │       │
          │  get_market         │       │
          │  → Flask /market    │       │
          │    hoặc vnstock API │       │
          │    (cache 60 giây)  │       │
          │                     │       │
          │  search_bds         │       │
          │  → Embedding query  │       │
          │    (LRU cache)      │       │
          │  → pgvector HNSW    │       │
          │    ef_search=60     │       │
          │  → SQL filter:      │       │
          │    city + district  │       │
          │                     │       │
          │  search_news        │       │
          │  → Embedding query  │       │
          │    (LRU cache)      │       │
          │  → ChromaDB query   │       │
          │    + category filter│       │
          │  → Keyword scoring  │       │
          │  → RRF merge        │       │
          │                     │       │
          │  get_prediction     │       │
          │  → Flask /ml/predict│       │
          │    (cache 30 phút)  │       │
          │                     │       │
          │  Kết quả → thêm     │       │
          │  ToolMessage vào    │       │
          │  state.messages     │       │
          └──────────┬──────────┘       │
                     │ quay lại llm     │
                     └──→ llm ◄─────────┘
                     (tối đa 10 vòng)
                            │
                            ▼
                  ┌────────────────────┐
                  │    save_memory     │
                  │                   │
                  │  Spawn background  │
                  │  thread → return  │
                  │  ngay (user không │
                  │  phải đợi)        │
                  │                   │
                  │  [background]     │
                  │  GPT-4o-mini trích│
                  │  xuất sở thích    │
                  │  → merge với      │
                  │    memory cũ      │
                  │    (max 300 chars)│
                  │  → PostgresStore  │
                  └──────────┬────────┘
                             │
                             ▼
                        ┌─────────┐
                        │ __end__ │
                        │         │
                        │  Flask  │
                        │  stream │
                        │  SSE về │
                        │  browser│
                        └─────────┘
```

---

## Parallel Tool Calls — Điểm khác biệt quan trọng

Với `parallel_tool_calls=True`, GPT-4o-mini có thể quyết định gọi nhiều tool trong **1 lần LLM call**. Toàn bộ tool chạy đồng thời trong ToolNode:

```
User: "giá vàng và dự đoán xu hướng vàng?"

LLM call 1:
  tool_calls = [
    get_commodity(item="gold"),      ──┐ chạy song song
    get_prediction(topic="gold")     ──┘ trong ToolNode
  ]

ToolNode: 2 tool chạy đồng thời → ~300ms thay vì ~600ms

LLM call 2: nhận cả 2 kết quả → viết câu trả lời tổng hợp
```

So sánh với sequential (cũ):
```
LLM call 1 → tool 1 → LLM call 2 → tool 2 → LLM call 3 → response
= 3 LLM calls

Parallel (hiện tại):
LLM call 1 → [tool 1 + tool 2] → LLM call 2 → response
= 2 LLM calls
```

---

## Ví dụ qua từng trường hợp

### Case 1: Câu hỏi đơn giản
**User:** "Thời tiết Hà Nội hôm nay?"

```
route_start     → 1 msg → inject_memory
inject_memory   → không có memory → skip
llm             → 1 tool_call: get_weather("Hà Nội")
tools           → gọi Open-Meteo → "32°C, Có mây..."
llm (lần 2)     → viết câu trả lời tự nhiên
route_after_llm → in-scope → save_memory
save_memory     → spawn thread → return ngay
__end__         → Flask stream về browser
```

### Case 2: Multi-task với parallel tools
**User:** "ACB hôm nay thế nào và những ngày tới?"

```
llm (lần 1)     → 2 tool_calls CÙNG LÚC:
                  - get_market(symbol="ACB")
                  - get_prediction(topic="ACB")
tools           → 2 tool chạy song song (~60ms tổng)
llm (lần 2)     → tổng hợp: giá hôm nay + xu hướng dự đoán
```

### Case 3: BDS với city + district filter
**User:** "tôi có 10 tỷ muốn mua nhà ở Cầu Giấy 2 phòng ngủ"

```
llm             → search_bds("tôi có 10 tỷ muốn mua nhà ở Cầu Giấy 2 phòng ngủ")
tools           → search_bds:
                  1. _extract_city("cầu giấy") → city = "HN"
                  2. _extract_district("cầu giấy") → district_term = "Cầu Giấy"
                  3. embed_query_cached(query) → vector (LRU cache)
                  4. SQL: WHERE city='HN' AND district ILIKE '%Cầu Giấy%'
                          ORDER BY embedding <=> query_vec (HNSW)
                          LIMIT 10
                  5. Fallback: nếu không có → bỏ district filter, giữ city
```

### Case 4: Hybrid news search
**User:** "tin tức thể thao mới nhất"

```
llm             → search_news(query="tin tức thể thao", category="thể thao")
tools           → search_news:
                  1. cat_id = _CATEGORY_MAP["thể thao"] → "p8"
                  2. embed_query_cached(query) → vector (LRU cache)
                  3. ChromaDB query với where={"category": {"$eq": "p8"}}
                  4. Keyword scoring: đếm query terms trong title/summary
                  5. RRF merge: score = 1/(60+sem_rank) + 1/(60+kw_rank)
                  6. Trả về top 5 kết quả được xếp hạng tổng hợp
```

### Case 5: History dài
**User:** lần thứ 11+ chat

```
route_start     → 12 msgs → summarize
summarize       → GPT-4o-mini tóm tắt 6 msgs cũ → 3 câu
                  giữ 6 msgs gần nhất
inject_memory   → thêm memory user (nếu có)
llm             → nhận: summary + 6 msgs (thay vì 12 msgs)
                  → context ngắn hơn → nhanh hơn, rẻ hơn
```

### Case 6: Out-of-scope
**User:** "Bạn là ai?" / "Xin chào"

```
llm             → không gọi tool, trả lời thẳng
route_after_llm → không tool_calls, topic="general" → __end__
                  (KHÔNG gọi save_memory → tiết kiệm 1 LLM call)
```

### Case 7: Recursion limit
**LLM bị loop gọi tool liên tục:**

```
llm → tools → llm → tools → llm → tools → ...
Sau 10 bước → LangGraph raise GraphRecursionError
→ Flask catch → trả lỗi cho user (không crash server)
```

---

## Tool → Nguồn dữ liệu

| Tool | Trigger | Nguồn dữ liệu | Cache |
|------|---------|--------------|-------|
| `get_weather` | thời tiết, nhiệt độ, mưa, gió | Open-Meteo API | 10 phút/city |
| `get_commodity` | vàng, SJC, DOJI, xăng, RON95 | Flask endpoints | 5 phút |
| `get_market` | chứng khoán, VNINDEX, mã CP | vnstock / TCBS | 60 giây |
| `search_bds` | nhà, căn hộ, đất, BDS, thuê/mua | pgvector HNSW | LRU embedding |
| `search_news` | tin tức, bài báo, sự kiện | ChromaDB hybrid | LRU embedding |
| `get_prediction` | xu hướng, dự đoán, tương lai | Flask ML endpoints | 30 phút |

---

## Caching Strategy

```
Tầng 1 — Embedding LRU cache (in-process):
  embed_query_cached(text) → @lru_cache(maxsize=256)
  Cùng query text → trả về vector đã tính, không chạy model lại
  Tiết kiệm: ~200-400ms per query

Tầng 2 — Tool result cache (in-process, time-based):
  get_market   → dict cache, TTL 60s per symbol
  get_commodity → dict cache, TTL 300s (gold/fuel)
  get_weather  → dict cache, TTL 600s per city
  get_prediction → Flask-level cache, TTL 1800s (fuel)

Tầng 3 — Server-side cache (Flask):
  /weather-proxy → cache Open-Meteo response 10 phút
  /ml/predict-fuel → cache 30 phút (tránh yfinance chậm)
```

---

## Lưu trữ

| Loại dữ liệu | Công nghệ | Chi tiết |
|---|---|---|
| Chat history | PostgreSQL (PostgresSaver) | Persist theo thread_id, không mất khi restart |
| Long-term memory | PostgreSQL (PostgresStore) | Sở thích user, merge tối đa 300 ký tự |
| BDS embeddings | PostgreSQL + pgvector | HNSW (m=16, ef_construction=64), vector(384) |
| News embeddings | ChromaDB | HNSW cosine space, filter theo categoryId |
| Observability | Langfuse (ClickHouse) | Trace LLM calls, tool calls, latency, token cost |

---

## Tại sao dùng LangGraph?

| Vấn đề | Code thẳng | LangGraph |
|--------|-----------|-----------|
| Tool gọi nhiều vòng | Tự viết vòng lặp phức tạp | Tự động loop llm → tools |
| Quản lý state | Truyền biến thủ công | State tự động qua nodes |
| Checkpointing | Tự implement | PostgresSaver tích hợp sẵn |
| Parallel tools | Phải dùng threading | `parallel_tool_calls=True` |
| Routing phức tạp | If/else lồng nhau | Conditional edges rõ ràng |
| Debug/trace | Log thủ công | Tích hợp Langfuse |
| Recursion guard | Tự implement | `recursion_limit` có sẵn |
