import requests
from langchain_core.tools import tool

FLASK_BASE = "http://localhost:5000"


@tool
def get_prediction(topic: str) -> str:
    """
    Lấy dự đoán xu hướng từ mô hình ML trên dashboard.
    Dùng khi user hỏi về dự đoán, xu hướng, tăng/giảm trong tương lai.

    Args:
        topic: chủ đề dự đoán. Các giá trị hợp lệ:
               - "gold"  : dự đoán giá vàng kỳ tới
               - "fuel"  : dự đoán giá xăng dầu kỳ tới
               - mã cổ phiếu bất kỳ: "VNM", "HPG", "VCB", "FPT", "VNINDEX"...
    """
    topic = topic.strip().upper()

    if topic in ("GOLD", "VÀNG", "GOLD_PRICE"):
        try:
            resp = requests.get(f"{FLASK_BASE}/ml/predict-gold", timeout=10)
            if resp.status_code == 503:
                return "Mô hình dự đoán vàng chưa sẵn sàng. Vui lòng thử lại sau."
            data = resp.json()
            direction = data.get("direction", "")
            pct       = data.get("change_pct", 0)
            price_now = data.get("price_now", 0)
            price_pred= data.get("price_pred", 0)
            confidence= data.get("confidence", 0)
            arrow = "▲ TĂNG" if direction == "up" else "▼ GIẢM"
            return (
                f"🔮 Dự đoán giá vàng SJC kỳ tới:\n"
                f"  Xu hướng: {arrow} ({pct:+.2f}%)\n"
                f"  Giá hiện tại: {price_now:,.0f} VNĐ/lượng\n"
                f"  Giá dự đoán:  {price_pred:,.0f} VNĐ/lượng\n"
                f"  Độ tin cậy: {confidence:.0f}%\n"
                f"   Chỉ mang tính tham khảo, không phải tư vấn đầu tư."
            )
        except Exception as e:
            return f"Lỗi lấy dự đoán vàng: {e}"

    if topic in ("FUEL", "XĂNG", "DẦU", "XĂNG DẦU"):
        try:
            resp = requests.get(f"{FLASK_BASE}/ml/predict-fuel", timeout=15)
            if resp.status_code == 503:
                return "Mô hình dự đoán xăng dầu chưa sẵn sàng."
            data = resp.json()
            direction = data.get("direction", "")
            confidence= data.get("confidence", 0)
            reason    = data.get("reason", "")
            arrow = "▲ TĂNG" if direction == "up" else "▼ GIẢM"
            lines = [
                f"🔮 Dự đoán giá xăng dầu kỳ điều chỉnh tới:",
                f"  Xu hướng: {arrow}",
                f"  Độ tin cậy: {confidence:.0f}%",
            ]
            if reason:
                lines.append(f"  Lý do: {reason}")
            lines.append("   Chỉ mang tính tham khảo, không phải tư vấn đầu tư.")
            return "\n".join(lines)
        except Exception as e:
            return f"Lỗi lấy dự đoán xăng dầu: {e}"

    try:
        resp = requests.get(f"{FLASK_BASE}/ml/predict?symbol={topic}", timeout=10)
        if resp.status_code == 503:
            data = resp.json()
            return f"Mô hình dự đoán chưa sẵn sàng: {data.get('error', '')}"
        data = resp.json()
        direction  = data.get("direction", "")
        confidence = data.get("confidence", 0)
        price_now  = data.get("price_now", 0)
        arrow = "▲ TĂNG" if direction == "up" else "▼ GIẢM"
        return (
            f"🔮 Dự đoán {topic} phiên tới:\n"
            f"  Xu hướng: {arrow}\n"
            f"  Giá hiện tại: {price_now:,.2f}\n"
            f"  Độ tin cậy: {confidence:.0f}%\n"
            f"  Chỉ mang tính tham khảo, không phải tư vấn đầu tư."
        )
    except Exception as e:
        return f"Lỗi lấy dự đoán {topic}: {e}"
