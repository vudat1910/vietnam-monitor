# Vietnam Monitor — AGENTS.md

## Project là gì
Ứng dụng web dashboard tổng hợp thông tin thị trường Việt Nam theo thời gian thực,
bao gồm: tin tức, thời tiết, chứng khoán, giá vàng/xăng dầu, bất động sản,
và dự đoán xu hướng bằng Machine Learning.

## Cấu trúc thư mục
```
VIETNAM-MO.../
├── src/
│   ├── ml/                 # ML models: dự đoán cổ phiếu, vàng, xăng dầu
│   ├── real_estate/        # Dữ liệu và logic bất động sản
│   ├── commodity.js        # Giá vàng, xăng dầu real-time
│   ├── market.js           # Thị trường chứng khoán, mã cổ phiếu
│   ├── weather.js          # Dự báo thời tiết 5 ngày theo tỉnh/thành
│   ├── process_data.py     # Data pipeline: fetch, clean, transform
│   ├── index.html          # Entry point frontend
│   ├── lives.html          # Trang video live news
│   ├── data.json           # Dữ liệu tĩnh tổng hợp
│   └── location.json       # Danh sách tỉnh/thành phố Việt Nam + tọa độ
├── data.json               # Dữ liệu root
```

## Chức năng chính
| Module | File | Mô tả |
|---|---|---|
| Tin tức | `index.html` | Bài báo từ nhiều nguồn, click để đọc |
| Live news | `lives.html` | Video livestream tin tức |
| Thời tiết | `weather.js` | Dự báo 5 ngày, 63 tỉnh/thành |
| Chứng khoán | `market.js` | Mã cổ phiếu, biểu đồ real-time |
| Giá vàng/xăng | `commodity.js` | Giá real-time, cập nhật liên tục |
| ML dự đoán | `src/ml/` | Dự đoán tăng/giảm: cổ phiếu, vàng, xăng |
| Bất động sản | `src/real_estate` | Danh sách + chatbot tư vấn |
| Data pipeline | `process_data.py` | Fetch và xử lý dữ liệu từ nguồn ngoài |

## Stack
- **Frontend**: HTML/CSS/JavaScript thuần (ES6+), không dùng framework
- **Data pipeline**: Python 3.11+
- **ML**: Python (src/ml/)
- **Lưu trữ**: JSON thuần

## Lệnh thường dùng
```bash
# Chạy frontend
open with live server index.html

# Chạy data pipeline
python src/process_data.py

# Chạy ML prediction
python src/ml/predict.py
```

## Conventions
- Ngôn ngữ comment trong code: **tiếng Việt**
- Tiền tệ: VND (số nguyên, không dùng float)
- Nhiệt độ: Celsius
- Thời gian: UTC+7 (giờ Việt Nam), format ISO8601
- Tọa độ: GeoJSON chuẩn `[lng, lat]`, tham chiếu từ `location.json`

## Dữ liệu quan trọng
- `location.json`: danh sách 63 tỉnh/thành kèm tọa độ — dùng làm reference
  cho mọi module có liên quan đến địa lý
- `data.json`: cache dữ liệu tổng hợp, không sửa tay
