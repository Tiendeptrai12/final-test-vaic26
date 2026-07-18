# AI Product Comparison Advisor — Python Backend (llama_index + guardrails-ai)

Trợ lý AI so sánh và tư vấn sản phẩm theo nhu cầu thật của khách hàng.
Vietnam Innovation Challenge 2026 — đối tác Điện Máy Xanh.

**Bản này viết lại toàn bộ backend bằng Python**, áp dụng thật 2 thư viện:
- [`llama-index-core`](https://pypi.org/project/llama-index-core/) + `llama-index-llms-anthropic` — RAG cho bước diễn giải Top N (Module 3).
- [`guardrails-ai`](https://pypi.org/project/guardrails-ai/) — validate/sửa output LLM theo schema + validator tuỳ chỉnh (Module 4).

Cả hai đều cài qua `pip` (xem `backend_py/requirements.txt`) — không copy source repo của 2 thư viện vào dự án.

## Cấu trúc

```
docs/technical-spec.md     # Kiến trúc đầy đủ — mục 11 mô tả riêng bản Python này
backend_py/                # Backend Python (FastAPI + llama_index + guardrails-ai)
  data/products_detail.json    # Catalog DMX thật (119 category) — nguồn production DUY NHẤT
  schemas/dmx_registry.json    # Mapping field DMX -> canonical (BTC cung cấp)
  scripts/                     # (ở thư mục gốc) build_products_detail_json.py — chuẩn bị dữ liệu offline
frontend/                  # Chat UI (bản mới — sidebar lịch sử, dark mode, thẻ sản phẩm), gọi API thật
```

## Cách chạy

Yêu cầu: Python >= 3.11.

```bash
cd backend_py
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

pytest -q
# Kỳ vọng: 92 passed — không cần API key, mọi lời gọi LLM trong test đều
# dùng CustomLLM giả lập của llama_index (không gọi mạng).
```

## Chạy server thật (cần API key)

```bash
cd backend_py
cp .env.example .env
# Mở .env, điền LLM_API_KEY=<key thật của bạn>

uvicorn app.server:app --reload --port 3000
# Mở http://localhost:3000 — frontend được serve kèm luôn
```

`app/explanation/llm_factory.py` đọc config LLM từ `.env`, không hardcode key/provider ở bất kỳ đâu.
Chọn nhà cung cấp qua biến `LLM_PROVIDER`:

| `LLM_PROVIDER` | Package | Ghi chú |
|---|---|---|
| `anthropic` (mặc định) | `llama-index-llms-anthropic` | `LLM_MODEL=claude-sonnet-4-6` |
| `deepseek` | `llama-index-llms-deepseek` | `LLM_MODEL=deepseek-chat`; `LLM_BASE_URL` tuỳ chọn, mặc định `https://api.deepseek.com` |
| `openai_like` | `llama-index-llms-openai-like` | Dùng cho bất kỳ API tương thích OpenAI chat completions nào chưa có package riêng — **bắt buộc** điền `LLM_BASE_URL` |

Ví dụ dùng DeepSeek — `backend_py/.env`:
```
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-xxxxxxxx
LLM_MODEL=deepseek-chat
```

Nếu thiếu key/base_url bắt buộc, server báo lỗi rõ ràng ngay khi cần gọi LLM (bước diễn giải Top N),
không âm thầm dùng giá trị rỗng. Bước hỏi làm rõ (NLU) vẫn chạy được nhờ fallback regex ngay cả khi
chưa cấu hình LLM.

## Trạng thái triển khai

- ✅ **Module 1 — Slot-filling & Conversation State**: tổng quát cho nhiều category qua `slot_schemas.py`, chống hỏi lặp, không âm thầm bỏ field sai.
- ✅ **Module 2 — Retrieval/Filter**: nạp & chuẩn hoá catalog từ **`backend_py/data/products_detail.json`** (dữ liệu DMX thật, 119 category, 13.754 sản phẩm), mapping qua `schemas/dmx_registry.json` (BTC cung cấp) — **không gọi `pd.read_excel` trong production**, mọi `source.type` = `"dmx_json"`. Category chưa có `spec_map` chi tiết (118/119, chỉ `air_conditioner` có) vẫn nạp & lọc theo ngân sách được, chưa lọc theo thông số kỹ thuật riêng.
- ✅ **Module 3 — Ranking + Explanation**: rule-based scoring tổng quát (không còn bug "category lạ rơi vào nhánh máy lạnh" của bản Node cũ) + gọi LLM diễn giải Top N qua **llama_index thật** (RAG trên context đã lọc sẵn, có `source_nodes` truy vết).
- ✅ **Module 4 — Validation/Guardrail**: dùng **guardrails-ai thật** (`Guard.for_pydantic` + custom validator `ClaimsVerified`) đối chiếu claim số của LLM với dữ liệu gốc, tự sửa/loại bỏ sai lệch.
- ✅ 92 test (pytest) — bao gồm test tích hợp toàn pipeline với LLM giả lập "trung thực" và "bịa dữ liệu" để xác nhận guardrail chặn đúng.

Chi tiết đầy đủ: [`docs/technical-spec.md`](docs/technical-spec.md) mục 11.
