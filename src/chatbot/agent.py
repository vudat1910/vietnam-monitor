import os
import json
import threading
from typing import Annotated, Literal, TypedDict, Optional
from dotenv import load_dotenv
from langchain_core.messages import (
    BaseMessage, SystemMessage, HumanMessage, AIMessage, trim_messages
)
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph

load_dotenv()
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from .prompts import SYSTEM_PROMPT
from .tools import search_bds, get_market, get_commodity, search_news, get_weather, get_prediction

os.environ["LANGCHAIN_TRACING_V2"] = "false"  

DB_URI = "postgresql://postgres@127.0.0.1:5432/postgres"


_langfuse_handler = None
_langfuse_init_done = False

def _get_langfuse_handler():
    """
    Singleton: chỉ khởi tạo 1 lần khi server start.
    Tránh overhead tạo mới handler mỗi LLM call (~50-200ms/call).
    """
    global _langfuse_handler, _langfuse_init_done
    if _langfuse_init_done:
        return _langfuse_handler
    _langfuse_init_done = True
    try:
        try:
            from langfuse.callback import CallbackHandler
        except ImportError:
            from langfuse.langchain import CallbackHandler
        _langfuse_handler = CallbackHandler()
        print("[LANGFUSE] Handler khởi tạo OK")
    except Exception as e:
        print(f"[LANGFUSE] Không kết nối được: {e}")
        _langfuse_handler = None
    return _langfuse_handler


class ChatState(TypedDict):
    messages:        Annotated[list[BaseMessage], add_messages]
    reflection_done: bool           
    summary:         Optional[str]  


_llm_primary = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.3,
    openai_api_key=os.environ.get("OPENAI_API_KEY"),
    max_retries=2,
)

_llm = _llm_primary  
_tools = [search_bds, get_market, get_commodity, search_news, get_weather, get_prediction]
_llm_with_tools          = _llm_primary.bind_tools(_tools, parallel_tool_calls=True)
_llm_fallback_with_tools = _llm_with_tools  


_TOPIC_KEYWORDS = {
    "bds":       ["nhà", "căn hộ", "đất", "bất động sản", "phòng ngủ", "thuê", "mua nhà", "chung cư"],
    "market":    ["cổ phiếu", "vnindex", "vn30", "hnx", "upcom", "chứng khoán", "mã", "sàn"],
    "commodity": ["vàng", "sjc", "doji", "xăng", "dầu", "ron", "nhiên liệu"],
    "news":      ["tin tức", "tin", "bài báo", "thông tin", "sự kiện", "mới nhất"],
    "weather":   ["thời tiết", "nhiệt độ", "mưa", "gió", "dự báo", "nắng", "lạnh", "nóng"],
}
_TOPIC_CONTEXT = {
    "bds":       "User đang hỏi về bất động sản. Ưu tiên hiển thị: giá, diện tích, số phòng, địa chỉ, link.",
    "market":    "User đang hỏi về chứng khoán. Ưu tiên hiển thị: giá hiện tại, % thay đổi, thời gian cập nhật.",
    "commodity": "User đang hỏi về giá hàng hóa. Ưu tiên hiển thị: giá mua/bán, đơn vị, thời gian.",
    "news":      "User đang hỏi về tin tức. Ưu tiên hiển thị: tiêu đề, tóm tắt, link bài báo, chuyên mục.",
    "weather":   "User đang hỏi về thời tiết. Ưu tiên hiển thị: nhiệt độ, mưa, gió, dự báo theo ngày.",
    "general":   "",
}

_IN_SCOPE_TOPICS = {"bds", "market", "commodity", "news", "weather"}

def _detect_topic(text: str) -> str:
    text_lower = text.lower()
    for topic, keywords in _TOPIC_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return topic
    return "general"


def summarize_history(state: ChatState):
    messages = state["messages"]
    if len(messages) <= 10:
        return {}

    recent   = messages[-6:]   
    old_msgs = messages[:-6]   

    history_text = "\n".join(
        f"{'User' if isinstance(m, HumanMessage) else 'Bot'}: {m.content[:300]}"
        for m in old_msgs
        if isinstance(m, (HumanMessage, AIMessage)) and m.content
    )
    if not history_text.strip():
        return {}

    summary_response = _llm.invoke([
        SystemMessage(content=(
            "Tóm tắt ngắn gọn cuộc hội thoại dưới đây bằng tiếng Việt (tối đa 3-4 câu). "
            "Giữ lại: tên BDS, mã cổ phiếu, giá cụ thể, kết quả user đã xem, chủ đề user quan tâm. "
            "Bỏ qua lời chào và câu không có thông tin."
        )),
        HumanMessage(content=history_text),
    ])

    return {
        "summary":  summary_response.content,
        "messages": recent,  
    }


def inject_memory(state: ChatState, store, config):
    thread_id = config["configurable"].get("thread_id", "anonymous")
    try:
        memory_item = store.get(("memory", thread_id), "user_interests")
        if memory_item and memory_item.value:
            interests = memory_item.value.get("topics", "")
            if interests:
                return {
                    "messages": [SystemMessage(
                        content=f"[Thông tin về user này]: {interests}"
                    )]
                }
    except Exception:
        pass
    return {}


def call_llm(state: ChatState):
    messages = state["messages"]

    last_human = next(
        (m.content for m in reversed(messages) if isinstance(m, HumanMessage)), ""
    )
    topic      = _detect_topic(last_human)
    topic_hint = _TOPIC_CONTEXT.get(topic, "")

    system_content = SYSTEM_PROMPT
    if topic_hint:
        system_content += f"\n[Gợi ý cho câu hỏi này]: {topic_hint}"

    context = [SystemMessage(content=system_content)]

    summary = state.get("summary")
    if summary:
        context.append(SystemMessage(content=f"[Tóm tắt hội thoại trước]: {summary}"))

    trimmed = trim_messages(
        messages,
        strategy="last",
        max_tokens=10,
        token_counter=lambda msgs: len(msgs),
        start_on="human",
        include_system=False,
    )
    context += trimmed

    lf_handler = _get_langfuse_handler()
    callbacks  = [lf_handler] if lf_handler else []

    try:
        response = _llm_with_tools.invoke(context, config={"callbacks": callbacks})
    except Exception as e:
        if "429" in str(e) or "rate" in str(e).lower():
            print("[LLM] Rate limit 70b → fallback 8b")
            response = _llm_fallback_with_tools.invoke(context, config={"callbacks": callbacks})
        else:
            raise

    return {
        "messages":        [response],
        "reflection_done": state.get("reflection_done", False),
    }


def _do_save_memory(last_human: str, thread_id: str, store):
    """Hàm thực thi thực sự, chạy trong background thread."""
    try:
        extract = _llm.invoke([
            SystemMessage(content=(
                "Từ câu hỏi của user, tóm tắt những gì user quan tâm "
                "(chủ đề, địa điểm, giá, mã cổ phiếu,...). "
                "Tối đa 1-2 câu tiếng Việt. Nếu không có gì hữu ích → trả về rỗng."
            )),
            HumanMessage(content=last_human),
        ])

        interest = extract.content.strip()
        if not interest:
            return

        try:
            existing   = store.get(("memory", thread_id), "user_interests")
            old_topics = existing.value.get("topics", "") if existing else ""
        except Exception:
            old_topics = ""

        merged = f"{old_topics} | {interest}".strip(" |")
        if len(merged) > 300:
            merged = merged[-300:]

        store.put(("memory", thread_id), "user_interests", {"topics": merged})
        print(f"[MEMORY] Đã lưu memory cho {thread_id}")

    except Exception as e:
        print(f"[MEMORY] Không lưu được: {e}")


def save_memory_background(last_human: str, thread_id: str, store):
    """Spawn background thread để lưu memory mà không block response."""
    t = threading.Thread(
        target=_do_save_memory,
        args=(last_human, thread_id, store),
        daemon=True, 
    )
    t.start()


def route_start(state: ChatState) -> Literal["summarize", "inject_memory"]:
    if len(state["messages"]) > 10:
        return "summarize"
    return "inject_memory"


def route_after_llm(state: ChatState) -> Literal["tools", "save_memory", "__end__"]:
    """
    Sau khi LLM trả lời:
    - Có tool_calls → chạy tools
    - Không có tool_calls, câu hỏi in-scope → save_memory (background)
    - Không có tool_calls, câu hỏi out-of-scope → kết thúc ngay (không tốn LLM call)
    """
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"

    last_human = next(
        (m.content for m in reversed(state["messages"])
         if isinstance(m, HumanMessage) and not m.content.startswith("[Hệ thống:")),
        ""
    )
    topic = _detect_topic(last_human)
    if topic in _IN_SCOPE_TOPICS:
        return "save_memory"
    return "__end__"


def save_memory(state: ChatState, store, config):
    thread_id = config["configurable"].get("thread_id", "anonymous")
    if thread_id == "anonymous":
        return {}

    last_human = next(
        (m.content for m in reversed(state["messages"])
         if isinstance(m, HumanMessage) and not m.content.startswith("[Hệ thống:")),
        ""
    )
    if not last_human:
        return {}

    save_memory_background(last_human, thread_id, store)
    return {}


_builder = StateGraph(ChatState)
_builder.add_node("summarize",     summarize_history)
_builder.add_node("inject_memory", inject_memory)
_builder.add_node("llm",           call_llm)
_builder.add_node("tools",         ToolNode(_tools))
_builder.add_node("save_memory",   save_memory)

_builder.set_conditional_entry_point(route_start)
_builder.add_edge("summarize",     "inject_memory")
_builder.add_edge("inject_memory", "llm")
_builder.add_conditional_edges("llm",   route_after_llm)
_builder.add_edge("tools",         "llm")
_builder.add_edge("save_memory",   "__end__")


def _build_graph():
    try:
        from langchain_core.caches import InMemoryCache
        from langchain_core.globals import set_llm_cache
        set_llm_cache(InMemoryCache())
    except Exception:
        pass

    try:
        import psycopg
        from langgraph.checkpoint.postgres import PostgresSaver
        from langgraph.store.postgres import PostgresStore

        conn_cp    = psycopg.connect(DB_URI, autocommit=True)
        conn_store = psycopg.connect(DB_URI, autocommit=True)

        checkpointer = PostgresSaver(conn_cp)
        checkpointer.setup()

        store = PostgresStore(conn_store)
        store.setup()

        print("[AGENT] PostgresSaver + PostgresStore OK")
        return _builder.compile(checkpointer=checkpointer, store=store)

    except Exception as e:
        print(f"[AGENT] PostgreSQL không khả dụng, dùng InMemorySaver: {e}")
        from langgraph.checkpoint.memory import InMemorySaver
        return _builder.compile(checkpointer=InMemorySaver())


graph = _build_graph()


def chat(user_message: str, thread_id: str = "anonymous"):
    """
    Gửi message và nhận câu trả lời.
    thread_id = user_id từ JWT → mỗi user có history + memory riêng.
    """
    config = {
        "configurable":   {"thread_id": thread_id},
        "recursion_limit": 10,  
    }

    lf_handler = _get_langfuse_handler()
    if lf_handler:
        try:
            lf_handler.session_id = thread_id
        except Exception:
            pass

    result = graph.invoke(
        {
            "messages":        [HumanMessage(content=user_message)],
            "reflection_done": False,
            "summary":         None,
        },
        config,
    )
    return result["messages"][-1].content, result["messages"]
