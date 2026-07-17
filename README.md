# VAIC 26 — AI Product Comparison Advisor (Điện Máy Xanh)

> Trợ lý AI so sánh và tư vấn sản phẩm theo nhu cầu thật của khách hàng.
> Vietnam Innovation Challenge 2026 · Track: Năng Suất SME Thông Minh.

## Quick Start

### 1. Clone & cài đặt

```bash
pip install -r requirements.txt
```

### 2. Cấu hình `.env`

Tạo file `.env` tại thư mục gốc:

```
FPT_API_KEY=your_fpt_ai_api_key_here
```

### 3. Chạy server

```bash
python backend.py
```

Server khởi động tại `http://localhost:8000`.

- API docs: `http://localhost:8000/docs`
- Health check: `GET /api/health`
- Chat endpoint: `POST /api/chat` — body: `{"query": "Tìm máy lạnh inverter cho phòng 15m2"}`

### 4. Chạy ETL Pipeline (xử lý dữ liệu BTC catalog)

```bash
python scripts/build_btc_catalog.py \
    --input data/raw/Spec_cate_gia.xlsx \
    --outdir data/processed \
    --report artifacts/btc_quality_report.json
```

Xử lý 1 sheet cụ thể:

```bash
python scripts/build_btc_catalog.py --sheet "Máy lạnh"
```

### 5. Chạy tests

```bash
python -m pytest tests/ -v
```

## Cấu trúc dự án

```
├── antigravity/            # Core business logic
│   ├── __init__.py         # Path setup (LlamaIndex, Guardrails)
│   ├── core.py             # ProductAdvisor — query pipeline
│   ├── btc_catalog.py      # JSONL catalog loader + validator
│   └── .agents/            # Agent configs (researcher, guard)
├── frontend/               # Static web UI (served by FastAPI)
├── scripts/
│   ├── build_btc_catalog.py  # Stage 2: ETL cleaner/extractor
│   ├── gen_schemas.py        # Stage 1: schema generator
│   └── validate_schemas.py   # Schema validation
├── schemas/                # JSON schemas (14 categories)
├── data/
│   ├── raw/                # Source Excel workbook
│   └── processed/          # Output JSONL + eligible JSON
├── tests/                  # pytest test suite
├── backend.py              # FastAPI entry point
├── requirements.txt        # Python dependencies
└── .env                    # API keys (not in git)
```

## API Endpoints

| Method | Path | Mô tả |
|--------|------|--------|
| `GET` | `/api/health` | Health check + API key status |
| `POST` | `/api/chat` | Chat query — nhận `{"query": "..."}`, trả kết quả tư vấn |
| `GET` | `/` | Frontend static files |

## Catalog Pipeline

1. **Stage 1** (`gen_schemas.py`): Đọc header Excel, sinh `registry.json` + JSON schemas cho 14 danh mục
2. **Stage 2** (`build_btc_catalog.py`): Normalize, parse, output JSONL + quality report
3. **Loader** (`btc_catalog.py`): Load JSONL với schema validation — bật qua `CATALOG_SOURCE=btc`

## Deployment

Hai luồng chạy song song — **on-prem** (bản chấm feasibility theo brief) và **Vercel** (bản public để demo/chia sẻ).

### On-prem (uvicorn)

Bản gốc theo yêu cầu brief. Chạy `python backend.py` (mục Quick Start). Toàn quyền dữ liệu, không rời máy chủ nội bộ.

### Vercel (public demo)

Serverless adapter tại `api/index.py` (không dùng `backend.py`). Vercel phục vụ `frontend/` tĩnh; Python chỉ chạy cho `/api/*` (xem `vercel.json`).

- **Chạy path mock** (`antigravity/core.py`) → **KHÔNG** cần/không bundle dữ liệu BTC → an toàn NDA. `.vercelignore` + `.gitignore` chặn `data/`, `.env`, Excel rời máy.
- **API key:** đặt `FPT_API_KEY` là **Environment Variable** trong Vercel (Project → Settings → Environment Variables). KHÔNG commit key, KHÔNG để lộ ra browser — backend gọi FPT server-side.

Deploy:

```bash
# 1. Cài Vercel CLI (một lần)
npm i -g vercel

# 2. Từ thư mục gốc repo
vercel                 # preview deploy
vercel --prod          # production

# 3. Set secret (hoặc làm trong dashboard)
vercel env add FPT_API_KEY
```

Hoặc dùng **Git integration**: import repo vào Vercel — chỉ file đã commit được đẩy (data không commit → không lộ). Nhớ set `FPT_API_KEY` trong dashboard.

> **Lưu ý serverless:** cold-start khởi tạo lại mỗi invocation → không preload catalog như on-prem. Với mock path điều này không ảnh hưởng. Khi chuyển sang BTC path thật, cân nhắc external storage cho `data/` (không commit) + giữ latency SLA.

## License

Internal project — Vietnam Innovation Challenge 2026.
