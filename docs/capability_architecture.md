# Capability Architecture — DMX AI Advisor

Bản logic hoàn chỉnh để team chốt trước khi vẽ Figma board. Ba tầng: **Giá trị trải nghiệm**
(user cảm nhận gì) → **Capabilities** (tech build module gì) → **Scenario chains** (mỗi nhu cầu
đi qua capability nào, theo thứ tự tiên quyết).

---

## 1. Giá trị trải nghiệm

- **Hiểu đúng tôi** — user nói ngôn ngữ đời thường; AI chuyển hoàn cảnh, ngân sách, nỗi lo
  thành tiêu chí sản phẩm có cấu trúc.
- **Giúp tôi hiểu vừa đủ** — AI giải thích đúng khái niệm ảnh hưởng quyết định, không dump
  toàn bộ thông số.
- **Đứng về phía tôi** — AI đánh giá giá trị tăng thêm so với tiền tăng thêm; có thể khuyên
  mẫu rẻ hơn, chưa cần nâng cấp, hoặc chưa nên mua.
- **Giúp tôi chốt tự tin** — AI so sánh theo hoàn cảnh cá nhân, giải thích trade-off, đưa
  decision rule rõ ràng.

---

## 2. Capabilities & build-status

| Cap | Vai trò | Module hiện tại | Trạng thái |
|-----|---------|-----------------|-----------|
| **C0 Scenario Router** | Phân loại ý định mỗi message (khám phá / xem model / compare / học / compatibility / nâng cấp / what-if / chọn). Mọi message qua Router, KHÔNG reset state. | `router.route` (9 intent + category→ranker) | ✅ |
| **C1 Understand Context** | Tạo/cập nhật Need Profile (category, hoàn cảnh, người dùng, ngân sách, hard/soft constraint, priority, shortlist, current product, bundle, location). Prerequisite mọi recommendation cá nhân hóa. | `nlu.extract_need_profile`, `merge_profiles` | ✅ |
| **C2 Clarify Need** | Chỉ chạy khi C1 thiếu critical field. Tối đa 3 lượt; Yes/No không tính lượt; dừng khi đủ; không hỏi lại data đã có. Output → C1. | `nlu.missing_slots`, `followups` | ✅ |
| **C3 Search / Exact Lookup** | Search: candidate từ Need Profile. Exact: lấy model/URL/product_id cụ thể. Cần category hoặc product reference hợp lệ. | `vector_db.search_products` (semantic), exact = id/url | ✅ |
| **C4 Filter** | Loại SP vi phạm hard constraint (vượt ngân sách cứng, sai công suất/kích thước, thiếu must-have, có must-not-have, hết hàng nếu stock bắt buộc). Output: valid / rejected / failed constraints. | `aircon_ranking.filter_candidates` | ✅ |
| **C5 Rank / Rerank** | Rank: xếp hạng lần đầu theo priority + soft preference. Rerank: khi user đổi ưu tiên mềm, pool vẫn hợp lệ (không search lại). | `rank_top`, `fpt_services.rerank` (bge), `comparison.priority_rerank_query` | ✅ |
| **C6 Compare / Evaluate** | ≥2 SP; 1 SP + nhu cầu; current vs upgrade; 2 item compatibility. Mode: contextual comparison, product-fit, compatibility, incremental-upgrade. | `comparison.compare` (contextual) | 🟡 compare ✅; fit/compat/upgrade TODO |
| **C7 Advise** | Biến kết quả kỹ thuật → kết luận mua: chọn nào, mẫu rẻ đủ chưa, tiền tăng thêm mua được gì, tính năng nào không đáng, nâng cấp hay chờ, đủ bằng chứng chưa. **Luôn đứng sau ≥1 của: Rank / Compare / Fit / Compatibility / Upgrade.** KHÔNG advise từ input thô. | `explainer.explain_top` | ✅ |
| **C8 Explain / Teach** | Support ngang. Explain: vì sao chọn/loại, vì sao ranking đổi, nguồn data. Teach: giải thích Inverter/BTU/RAM/Hz, khi nào đáng trả thêm. Chỉ giải thích *decision* khi đã có score/evidence. | `reasons[]` (explain); `teach.teach` (glossary + gate) | ✅ |
| **C9 Decide / Handoff** | Xác nhận SP, tóm tắt lý do + trade-off đã chấp nhận + data còn thiếu; lưu/chia sẻ/**link ra DMX** (advisor KHÔNG xử lý order/ship/payment). | link DMX (`item.url`), `accessory` cross-sell | 🟡 UI-only |
| **C10 Recovery** | Kích hoạt khi: 0 candidate / thiếu data / yêu cầu mâu thuẫn / compatibility fail / không thể recommend tin cậy. Không tự sửa nhu cầu — đưa option cho user. | `_relaxation_steps`, `no_results_terminal` | ✅ |

**Còn thiếu build:** C6 (fit/compat/upgrade eval). (C0 Router ✅ · C8 Teach ✅ · phone ranking ✅)

---

## 3. Dependency rules (điều kiện tiên quyết)

| Capability | Tiên quyết |
|-----------|-----------|
| Clarify | Có Need Profile nhưng thiếu critical field |
| Search | Có category + đủ critical field |
| Exact Lookup | Có model / URL / product_id |
| Filter | Search đã trả candidate |
| Rank | Có valid candidates + priority |
| Rerank | Đã có candidate pool + ranking trước |
| Compare | Có ≥2 product record |
| Fit Evaluation | Có exact product + Need Profile |
| Compatibility | Đủ 2 item + compatibility fields |
| Advise | Đã có Rank hoặc Evaluation result |
| Explain decision | Đã có score / evidence / comparison |
| Decide | Đã có Advice outcome + user xác nhận |

**Bất biến quan trọng nhất:** *Advise là capability hội tụ bắt buộc trước Decide.* Search,
Rank, Compare, Compatibility, Upgrade chỉ tạo **evidence**; Advise biến evidence thành quyết
định có nghĩa với user.

---

## 4. Flow tổng thể

```
User message → Scenario Router → chọn capability chain → Advise → outcome → user choice
             → Decide hoặc chuyển capability khác
```

Không phải scenario nào cũng chạy toàn bộ capability.

```
SCENARIO ROUTER
      ↓
UNDERSTAND CONTEXT
      ↓
CLARIFY (nếu thiếu)
      ↓
SEARCH / LOOKUP
      ↓
FILTER
      ↓
RANK  hoặc  COMPARE / EVALUATE
      ↓
ADVISE            ← hội tụ bắt buộc
      ↓
OUTCOME BRANCH → USER CHOICE → DECIDE hoặc capability tiếp
```

---

## 5. Scenario chains

**A — Khám phá mơ hồ** ("Tôi muốn mua máy lạnh")
Router → Understand → Clarify → Search → Filter → Rank → Advise → Decision Board → Decide.
Nhánh: sau clarify vẫn thiếu critical field → giả định an toàn được không? Có → user xác nhận
→ Search; Không → tạm dừng, yêu cầu bổ sung.

**B — Nhu cầu đã cụ thể** ("Máy lạnh <15tr phòng ngủ 18m² ưu tiên êm")
Router → Understand → (đủ field? Có→Search / Không→Clarify) → Filter → Rank → Advise → Board.
Không bắt buộc dùng đủ 3 lượt clarify.

**C — Exact model / URL** ("Mẫu AQUA này hợp phòng tôi không?")
Router → Exact Lookup → Understand → Clarify nếu thiếu hoàn cảnh → Fit Evaluation → Advise →
Decide. Nếu chỉ hỏi giá/thông số → Exact Lookup → Explain (KHÔNG chạy recommendation pipeline).

**D — Compare shortlist** ("So sánh 2 tủ lạnh này")
Router → Exact Lookup 2 SP → Understand → Clarify priority nếu cần → Compare → Advise → Board →
Decide. **Compare luôn dẫn tới Advise** — không chỉ đưa bảng khác biệt, bước sau bắt buộc kết
luận: A hợp hơn khi nào, B khi nào, user hiện tại nên chọn gì.

**E — Học thông số** ("Inverter là gì?") — **NHÁNH PHỤ, KHÔNG main-chain** *(đã điều chỉnh)*
- C8 Teach chỉ kích hoạt khi **user yêu cầu rõ** ("X là gì / giải thích X / nghĩa là sao").
  Router KHÔNG tự route vào Teach; Teach KHÔNG tự chảy vào Search/Rank.
- Định nghĩa thuần (chưa có product/budget): **trả định nghĩa ngắn NGAY**, rồi gợi ý gắn vào
  việc mua ("bạn đang xem máy nào, ngân sách bao nhiêu để mình nói có đáng không").
- Câu hỏi *áp dụng/decision* ("có đáng trả thêm cho Inverter không"): chỉ trả lời khi đã có
  **thông số mặt hàng + ngân sách**; thiếu → hỏi đúng 2 field đó rồi mới kết luận grounded.

```
User: "Inverter là gì?"
Router → Teach (side)
  → định nghĩa ngắn ngay (grounded, khái niệm chuẩn)
  → gợi ý: gắn vào máy nào / ngân sách bao nhiêu?
     ├── User cung cấp → giải thích "có đáng với máy/ngân sách của bạn" (cần product spec + budget)
     └── User bỏ qua  → kết thúc learning flow (KHÔNG vào pipeline)
```

**F — Compatibility / bundle** ("Màn hình này hợp PC không?")
Router → Exact Lookup A+B → Compatibility Evaluation → Advise → Decide. Advice phân biệt: kết
nối được không / cần adapter không / khai thác hết tính năng không / có bottleneck không. Fail
→ user chọn: xem phụ kiện-adapter / tìm thay thế / giữ nguyên / kết thúc.

**G — Có đáng nâng cấp?** ("TV cũ vẫn dùng, có nên lên 55 inch?")
Router → Understand current product + pain → Search/Lookup alternatives → Compare incremental
benefit → Advise. Outcome: nên nâng cấp / chỉ đáng nếu cần tính năng X / mẫu rẻ đã đủ / chưa
nên / chưa đủ bằng chứng.

**H — Đổi ưu tiên** ("Tiết kiệm điện quan trọng hơn độ êm")
Router → Update Need Profile → soft hay hard change? Soft → Rerank → Advise → Board mới. Hard
(đổi ngân sách/diện tích/must-have) → Search lại → Filter → Rank → Advise.

**I — What-if** ("Nếu tăng ngân sách lên 18tr thì sao?")
Router → Clone Need Profile → đổi assumption trong state tạm → Search hoặc Rerank → Compare
cũ vs mới → Advise. User chọn: áp dụng / giữ cũ / thử scenario khác. **Không ghi đè state chính
trước khi user xác nhận.**

---

## 6. Outcome & consequence branches

1. **Có lựa chọn phù hợp** → Top 3 → Compare / Why / What-if / Select.
2. **Mẫu rẻ hơn đã đủ** → "Mẫu đắt hơn không khác biệt đáng kể với nhu cầu hiện tại" → xem mẫu
   đủ / vẫn so cao cấp / đổi ưu tiên.
3. **Không có candidate** → Recovery → xác định constraint fail → đề xuất tối đa 2 cách nới →
   user chọn nới / tự sửa / kết thúc. **KHÔNG tự tăng ngân sách.**
4. **Chưa nên nâng cấp** → chấp nhận & lưu / xem khi nào nên / vẫn xem thay thế.
5. **Thiếu dữ liệu** → nói rõ field nào thiếu → tiếp tục với độ chắc thấp hơn / cung cấp thêm /
   bỏ candidate thiếu data / kết thúc.
6. **Compatibility fail** → tìm item tương thích khác / thêm adapter / giảm kỳ vọng / giữ nguyên.

---

## 7. Decision Board (sau Advice)

Mọi recommendation chain hội tụ về một nơi:

```
Decision Board
├── Compare        → Compare → Advise
├── Why sel/rej    → Explain → quay lại Board
├── Learn          → Teach → quay lại Board
├── Đổi soft priority → Rerank → Advise
├── Đổi hard constraint → Search → Filter → Rank → Advise
├── What-if        → Scenario simulation → Advise
├── Compatibility  → Compatibility → Advise
└── Select         → Decide / Handoff
```

Mua/Lưu/Chia sẻ trong prototype ghi rõ **demo UI** nếu chưa tích hợp thật. Advisor không xử lý
order/ship/payment — chỉ link ra dienmayxanh.com + giới thiệu khuyến mãi/freeship.
