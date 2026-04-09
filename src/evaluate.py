import os
import requests
import json
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv()

FLASK_BASE = "http://localhost:5000"

TEST_CASES = [
    {
        "question":     "Giá vàng SJC hôm nay là bao nhiêu?",
        "ground_truth": "SJC",
        "topic":        "commodity",
    },
    {
        "question":     "VNINDEX đang ở mức bao nhiêu?",
        "ground_truth": "VNINDEX",
        "topic":        "market",
    },
    {
        "question":     "Tin tức công nghệ mới nhất?",
        "ground_truth": "công nghệ",
        "topic":        "news",
    },
    {
        "question":     "Giá xăng RON 95 hiện tại là bao nhiêu?",
        "ground_truth": "RON 95",
        "topic":        "commodity",
    },
    {
        "question":     "Nhà 3 phòng ngủ ở Hà Nội giá dưới 5 tỷ?",
        "ground_truth": "Hà Nội",
        "topic":        "bds",
    },
]


def ask_chatbot(question: str) -> str:
    """
    Gọi endpoint /chat, nhận SSE stream, ghép các token lại thành câu trả lời đầy đủ.
    SSE (Server-Sent Events): server gửi từng dòng "data: {...}" liên tục.
    """
    try:
        res = requests.post(
            f"{FLASK_BASE}/chat",
            json={"message": question},
            stream=True,   
            timeout=60,
        )
        full_text = ""
        for line in res.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8")
            if not decoded.startswith("data: "):
                continue  
            try:
                payload = json.loads(decoded[6:])  
                if payload.get("token"):
                    full_text += payload["token"]  
            except Exception:
                pass
        return full_text.strip()
    except Exception as e:
        return f"ERROR: {e}"


_judge_llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    groq_api_key=os.environ.get("GROQ_API_KEY"),
)

def llm_judge(question: str, answer: str, ground_truth: str) -> dict:
    prompt = f"""Chấm điểm câu trả lời của chatbot từ 1-10 theo 3 tiêu chí:
- Relevancy (liên quan đến câu hỏi): 1-10
- Faithfulness (không bịa, dựa trên data thực): 1-10
- Completeness (đầy đủ thông tin): 1-10

Câu hỏi: {question}
Câu trả lời: {answer}
Kỳ vọng phải chứa thông tin về: {ground_truth}

Trả lời theo format JSON:
{{"relevancy": X, "faithfulness": X, "completeness": X, "comment": "lý do ngắn gọn"}}"""

    response = _judge_llm.invoke([
        SystemMessage(content="Bạn là chuyên gia đánh giá chatbot. Chỉ trả về JSON, không giải thích thêm."),
        HumanMessage(content=prompt),
    ])

    try:
        text  = response.content
        start = text.find("{")
        end   = text.rfind("}") + 1
        return json.loads(text[start:end])
    except Exception:
        return {"relevancy": 0, "faithfulness": 0, "completeness": 0, "comment": "Không parse được JSON"}



def run_ragas(results: list) -> dict:
    try:
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, faithfulness
        from datasets import Dataset

        data = {
            "question":    [r["question"]    for r in results],
            "answer":      [r["answer"]      for r in results],
            "contexts":    [[r["question"]]  for r in results],
            "ground_truth": [r["ground_truth"] for r in results],
        }

        dataset = Dataset.from_dict(data)
        score   = evaluate(dataset, metrics=[answer_relevancy, faithfulness])
        return dict(score)

    except ImportError:
        print("[EVAL] Chưa cài ragas: pip install ragas datasets")
        return {}
    except Exception as e:
        print(f"[EVAL] RAGAS lỗi: {e}")
        return {}


def main():
    print("=" * 60)
    print("VIETNAM MONITOR — Chatbot Evaluation")
    print("=" * 60)

    results = []

    for i, case in enumerate(TEST_CASES, 1):
        question     = case["question"]
        ground_truth = case["ground_truth"]

        print(f"\n[{i}/{len(TEST_CASES)}] {question}")

        answer = ask_chatbot(question)
        print(f"  → {answer[:120]}...")

        scores = llm_judge(question, answer, ground_truth)
        print(f"  Relevancy={scores.get('relevancy')}/10  "
              f"Faithfulness={scores.get('faithfulness')}/10  "
              f"Completeness={scores.get('completeness')}/10")
        print(f"  Comment: {scores.get('comment', '')}")

        results.append({
            "question":    question,
            "answer":      answer,
            "ground_truth": ground_truth,
            "topic":       case["topic"],
            "scores":      scores,
        })

    print("\n" + "=" * 60)
    print("KẾT QUẢ TỔNG HỢP — LLM-as-Judge")
    print("=" * 60)
    for metric in ["relevancy", "faithfulness", "completeness"]:
        avg = sum(r["scores"].get(metric, 0) for r in results) / len(results)
        print(f"  {metric.capitalize():15s}: {avg:.1f}/10")

    print("\n[RAGAS] Đang tính metrics...")
    ragas_scores = run_ragas(results)
    if ragas_scores:
        print("KẾT QUẢ — RAGAS")
        for k, v in ragas_scores.items():
            print(f"  {k}: {v:.3f}")

    with open("evaluation_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\nĐã lưu chi tiết vào: evaluation_results.json")


if __name__ == "__main__":
    main()
