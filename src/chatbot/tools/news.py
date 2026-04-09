import os
import requests
import chromadb
from langchain_core.tools import tool
from ._embeddings import embed_query_cached

FLASK_BASE  = "http://localhost:5000"
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "../../../data/chroma_news")

_chroma_client = None
_collection    = None

_CATEGORY_MAP = {
    "thời sự":      "p1",  "chính trị":    "p1",
    "pháp luật":    "p2",  "tội phạm":     "p2",
    "sức khỏe":     "p3",  "y tế":         "p3",
    "đời sống":     "p4",  "xã hội":       "p4",
    "du lịch":      "p5",
    "kinh doanh":   "p6",  "kinh tế":      "p6",  "tài chính": "p6",
    "bất động sản": "p7",
    "thể thao":     "p8",  "bóng đá":      "p8",
    "giải trí":     "p9",  "showbiz":      "p9",  "nghệ sĩ":   "p9",
    "giáo dục":     "p10", "tuyển sinh":   "p10",
    "nội vụ":       "p11", "lao động":     "p11",
    "công nghệ":    "p12", "kỹ thuật số":  "p12",
    "thế giới":     "world-news", "quốc tế": "world-news",
}


def _get_collection():
    global _chroma_client, _collection
    if _collection is None:
        _chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = _chroma_client.get_or_create_collection(
            name="news",
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def index_news():
    try:
        resp = requests.get(f"{FLASK_BASE}/data", timeout=10)
        resp.raise_for_status()
        articles = resp.json()
    except Exception as e:
        print(f"[NEWS] Không fetch được tin tức: {e}")
        return

    if not articles:
        return

    collection = _get_collection()
    try:
        existing = collection.get()
        if existing["ids"]:
            collection.delete(ids=existing["ids"])
    except Exception:
        pass

    docs, ids, metas = [], [], []
    for i, article in enumerate(articles):
        title    = article.get("title", "")
        summary  = article.get("summary", "")
        url      = article.get("url", "")
        category = article.get("categoryId", "")
        if not title:
            continue
        text = f"{title}. {summary}".strip()
        docs.append(text)
        ids.append(f"news_{i}_{hash(url) % 100000}")
        metas.append({"title": title, "summary": summary, "url": url, "category": category})

    if not docs:
        return

    batch_size = 50
    for start in range(0, len(docs), batch_size):
        from ._embeddings import get_embeddings
        embeddings = get_embeddings().embed_documents(docs[start:start + batch_size])
        collection.add(
            documents=docs[start:start + batch_size],
            embeddings=embeddings,
            ids=ids[start:start + batch_size],
            metadatas=metas[start:start + batch_size],
        )
    print(f"[NEWS] Đã index {len(docs)} bài báo vào ChromaDB")


def _keyword_score(text: str, terms: list[str]) -> float:
    """Điểm keyword: tỉ lệ query terms xuất hiện trong title/summary."""
    if not terms:
        return 0.0
    t = text.lower()
    return sum(1 for term in terms if term in t) / len(terms)


@tool
def search_news(query: str, category: str = "", offset: int = 0) -> str:
    """
    Tìm kiếm tin tức bằng hybrid search (semantic + keyword, RRF merge).

    Args:
        query: nội dung tìm kiếm tự nhiên.
               "xem thêm"/"còn nữa" → giữ nguyên query cũ, tăng offset thêm 5.
        category: danh mục tin (LLM tự xác định từ ngữ cảnh, để trống nếu không rõ).
                  Các giá trị: "thể thao", "giải trí", "công nghệ", "thời sự",
                  "pháp luật", "sức khỏe", "đời sống", "du lịch", "kinh doanh",
                  "bất động sản", "giáo dục", "nội vụ", "thế giới"
        offset: bắt đầu từ bài thứ mấy (mặc định 0).
    """
    try:
        collection = _get_collection()
        if collection.count() == 0:
            index_news()
        if collection.count() == 0:
            return "Hiện chưa có tin tức trong hệ thống."

        cat_id = _CATEGORY_MAP.get(category.lower().strip(), "")

        query_vec = list(embed_query_cached(query))
        n_fetch   = min(40, collection.count())

        where = {"category": {"$eq": cat_id}} if cat_id else None
        try:
            sem_results = collection.query(
                query_embeddings=[query_vec],
                n_results=n_fetch,
                include=["metadatas", "distances"],
                where=where,
            )
        except Exception:
            sem_results = collection.query(
                query_embeddings=[query_vec],
                n_results=n_fetch,
                include=["metadatas", "distances"],
            )

        metadatas = sem_results.get("metadatas", [[]])[0]
        distances = sem_results.get("distances", [[]])[0]  

        if not metadatas:
            return f"Không tìm thấy tin tức về '{query}'."

        sem_rank = {i: rank for rank, i in enumerate(range(len(metadatas)))}

        query_terms = [t.strip() for t in query.lower().split() if len(t.strip()) > 1]
        kw_scores   = []
        for meta in metadatas:
            text  = f"{meta.get('title','')} {meta.get('summary','')}".lower()
            score = _keyword_score(text, query_terms)
            kw_scores.append(score)

        kw_ranked = sorted(range(len(kw_scores)), key=lambda i: kw_scores[i], reverse=True)
        kw_rank   = {idx: rank for rank, idx in enumerate(kw_ranked)}

        K = 60
        rrf_scores = []
        for i in range(len(metadatas)):
            score = 1 / (K + sem_rank[i]) + 1 / (K + kw_rank[i])
            rrf_scores.append((score, i))

        rrf_scores.sort(reverse=True)
        ranked_metas = [metadatas[i] for _, i in rrf_scores]

        total    = len(ranked_metas)
        page     = ranked_metas[offset:offset + 5]
        has_more = (offset + 5) < total

        if not page:
            return "Không còn tin tức nào khác phù hợp."

        cat_label = f" [{category}]" if category else ""
        header    = f"📰 Tin tức{cat_label} về '{query}' (bài {offset+1}–{offset+len(page)}/{total}):\n"
        lines     = [header]
        for meta in page:
            title   = meta.get("title", "")
            summary = meta.get("summary", "")
            url     = meta.get("url", "")
            lines.append(f"• [{title}]({url})\n  {summary}")

        if has_more:
            lines.append(f"\n_(Còn {total - offset - 5} kết quả nữa.)_")

        return "\n\n".join(lines)

    except Exception as e:
        return f"Lỗi tìm kiếm tin tức: {str(e)}"
