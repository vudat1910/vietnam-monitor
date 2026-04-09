"""
Shared embedding singleton — load 1 lần, dùng chung cho bds.py và news.py.
Tránh mỗi module load lại model → tiết kiệm RAM và thời gian khởi động.
LRU cache cho embed_query_cached — cùng query không inference lại.
"""
from functools import lru_cache
from langchain_huggingface import HuggingFaceEmbeddings

_instance = None


def get_embeddings() -> HuggingFaceEmbeddings:
    global _instance
    if _instance is None:
        _instance = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    return _instance


@lru_cache(maxsize=256)
def embed_query_cached(text: str) -> tuple:
    """
    Cache embedding vector theo query text.
    Cùng câu hỏi → trả về vector đã tính, không inference lại (~200-400ms tiết kiệm).
    """
    return tuple(get_embeddings().embed_query(text))
