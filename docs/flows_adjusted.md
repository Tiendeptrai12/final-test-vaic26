# Flows (đã điều chỉnh) — Điện Máy Xanh AI Advisor

Điều chỉnh vs bản gốc: **bỏ stock** (data không có), **code quyết slot thiếu** (LLM chỉ diễn đạt câu hỏi),
**tie-break → giá thấp**, **ladder +10%/+25%** thay "+20%", **terminal khi 0 SP**, **scope = máy lạnh**,
annotate **latency 2 LLM call** trên path Top-3.

---

## 1. AI Flow (kỹ thuật)

```mermaid
flowchart TD
    open([Mở AI Assistant]) --> box[Ô nhập text<br/>mô tả / trả lời]
    clarify[Hiển thị câu hỏi làm rõ] --> box

    box --> A["LLM CALL A — Hiểu nhu cầu<br/>(reuse cho Call C)<br/>extract ý định + update state → JSON"]

    A -.->|"Rule prompt A: ngoài máy lạnh→từ chối lịch sự;<br/>explicit > implicit; tối đa hỏi lại 3 lần"| A

    A --> chkSlot{"CODE check slot thiếu<br/>(area_m2, budget_max)?"}
    chkSlot -->|"Chưa đủ (còn quota ≤3)"| phrase["LLM phrase câu hỏi làm rõ<br/>cho slot code báo thiếu"]
    phrase --> clarify
    chkSlot -->|"Đủ / hết quota hỏi"| filt["Structured query (CODE, no LLM)<br/>lọc theo spec cứng<br/>❌ KHÔNG lọc stock (data unknown)"]

    filt --> has{Có ≥1 SP<br/>sau khi lọc?}
    has -->|Không| relax["Rule cứng (CODE): relaxation ladder<br/>brand → sunny → budget +10% → +25% → area ±3m²"]
    relax --> reFilt{Ladder còn bước<br/>& vẫn 0 SP?}
    reFilt -->|Còn bước| filt
    reFilt -->|Hết ladder, vẫn 0| dead["TERMINAL: 'Chưa có SP phù hợp'<br/>+ gợi ý nới tiêu chí (KHÔNG bịa SP)"]

    has -->|Có| B["LLM CALL B — Xếp hạng + giải thích<br/>chấm điểm mềm trên tập đã lọc (no vector DB)<br/>→ Top 3 + lý do từ source_fields"]
    B -.->|"Rule prompt B: bằng điểm→GIÁ THẤP hơn (stock đã bỏ);<br/>không suy diễn số ngoài dataset"| B

    B --> top3[User xem Top 3 + phản hồi UI]

    top3 --> C["LLM CALL C (reuse code Call A)<br/>phân loại phản hồi:<br/>chốt / giải thích / lọc thêm / đổi hẳn"]
    C -->|Đổi hẳn tiêu chí| A
    C -->|Cần giải thích / lọc cụ thể hơn| B
    C -->|Chốt 1 SP| confirm[Xác nhận UI<br/>no backend giỏ hàng]
    confirm --> done[Mua / Lưu / Chia sẻ<br/>UI only cho demo]

    %% Latency budget: path 'Đủ → Top 3' = Call A + Call B tuần tự, phải < 5s
```

> **Latency:** path `đủ thông tin → Top 3` = **Call A + Call B** (2 LLM call tuần tự) → tổng phải < 5s (SLA).
> Ranking code ~3ms. Preload catalog lúc startup.

---

## 2. User Flow (trải nghiệm)

```mermaid
flowchart LR
    open([Mở AI Assistant]) --> input[Nhập mô tả nhu cầu -text-]
    input --> proc["Hệ thống đang xử lý..."]

    proc --> ask{AI cần hỏi thêm?}
    ask -->|Có| seeQ[Xem câu hỏi gợi ý từ AI] --> ansQ[Trả lời câu hỏi] --> proc
    ask -->|Không| hasP{Có sản phẩm<br/>phù hợp?}

    hasP -->|Có| top3[Xem Top 3 gợi ý<br/>kèm lý do]
    hasP -->|Không| loose[AI gợi ý nới tiêu chí<br/>vd: tăng ngân sách] --> agree[Đồng ý điều chỉnh] --> proc

    top3 --> react{Người dùng<br/>phản hồi gì?}
    react -->|"Cần biết thêm / lọc kỹ hơn"| more[Nêu yêu cầu cụ thể hơn<br/>vd: hãng, độ ồn] --> input
    react -->|Muốn đổi hẳn nhu cầu| input
    react -->|Ưng 1 sản phẩm| pick[Xác nhận lựa chọn]
    pick --> buy[Mua / Lưu / Chia sẻ]
```

---

### Ghi chú khớp guardrails (`antigravity/.agents/guard_agent.yaml`)
- `no_stock_claims` → nhánh stock đã xóa khỏi cả 2 flow.
- `clarification_budget` (max 3) → điều kiện quota trên nhánh "Chưa đủ".
- `scope_guard` → refuse ngoài máy lạnh (Rule prompt A).
- `code_rules.no_results_terminal` → box TERMINAL trong AI flow.
- `grounded_explanation` → "lý do từ source_fields" ở Call B.
