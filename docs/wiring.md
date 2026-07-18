# Wiring spec — Router → capabilities inside `nlu.build_chat_response`

How the built engines connect into one dispatch. Owner: `antigravity/nlu.py`. All engines are
already built + tested; this is the integration contract only. Golden rule stays: **the LLM
rewrites language, code owns facts** — prices/specs/items come only from the engines below.

## Entry

`build_chat_response(text, history=None, *, records=None, n=3, timeout=3.0, explain=True, prior_profile=None, selected_products=None)`

Add one param: `selected_products: list[dict] | None` — products the user referenced (for
compare / fit / compatibility / upgrade), resolved by the caller/UI or `vector_db.search_products`.

## Step 0 — Route (always)

```python
from antigravity import router
r = router.route(text)          # RouteResult(intent, category, ranker, is_comparison, abstract_need, has_constraints)
```
Router never resets state. `r.intent` picks the chain; `r.ranker` picks the ranking engine.

## Response contract (superset)

```
{ query, mode, message, profile, safety_checked,
  items[], questions[], relaxations[], explanation,   # recommendation
  comparison{}, evaluation{}, teach{} }               # mode-specific, else absent
```
`mode ∈ { need_info, recommendation, comparison, fit, compatibility, upgrade, teach, whatif, recovery }`.

## Dispatch table (by `r.intent`)

| intent | chain | engine call | mode |
|--------|-------|-------------|------|
| `teach` | C8 side branch | `teach.teach(text, has_product=?, has_budget=?)` | `teach` |
| `compare` | C6 contextual | `comparison.compare(selected_products)` → then Advise | `comparison` |
| `compatibility` | C6 | `evaluation.evaluate_compatibility(a, b)` → Advise | `compatibility` |
| `upgrade` | C6 | `evaluation.evaluate_upgrade(current, candidate)` → Advise | `upgrade` |
| `exact_lookup` | C3 exact + C6 fit | resolve product → `evaluation.evaluate_fit(product, **need)` | `fit` |
| `change_priority` | C5 rerank | merge profile → `rank`/`rerank` (no re-search) | `recommendation` |
| `what_if` | C5 sim | clone profile + apply assumption → rank → compare old/new | `whatif` |
| `specific_need` / `explore` | C1→C2→C3→C4→C5 | existing advise() path | `recommendation` / `need_info` |

**Invariant:** compare / fit / compatibility / upgrade **must be followed by Advise** (C7) —
never return a raw table/verdict; always add the buy-relevant conclusion.

## Reference implementation (top of `build_chat_response`)

```python
from antigravity import router, teach as teach_mod, comparison as cmp, evaluation as ev

r = router.route(text)

# --- C8 Teach: side branch, never enters the pipeline ---
if r.intent == router.INTENT_TEACH:
    prof = prior_profile or {}
    t = teach_mod.teach(text, has_product=bool(prof.get("_product")),
                        has_budget=prof.get("budget_max") is not None)
    return {"query": text, "mode": "teach", "message": t["message"],
            "teach": t, "profile": prof, "safety_checked": True}

# --- C6 Compare (needs >=2 resolved products) ---
if r.intent == router.INTENT_COMPARE and selected_products and len(selected_products) >= 2:
    comp = cmp.compare(selected_products)
    return {"query": text, "mode": "comparison", "comparison": comp,
            "message": _advise_from_comparison(comp),   # C7: kết luận A/B khi nào, nên chọn gì
            "profile": prior_profile or {}, "safety_checked": True}

# --- C6 Compatibility ---
if r.intent == router.INTENT_COMPATIBILITY and selected_products and len(selected_products) >= 2:
    comp = ev.evaluate_compatibility(selected_products[0], selected_products[1])
    return {"query": text, "mode": "compatibility", "evaluation": comp,
            "message": comp["note"], "safety_checked": True}   # + Advise: adapter? bottleneck?

# --- C6 Upgrade ---
if r.intent == router.INTENT_UPGRADE and selected_products and len(selected_products) >= 2:
    comp = ev.evaluate_upgrade(selected_products[0], selected_products[1])
    return {"query": text, "mode": "upgrade", "evaluation": comp,
            "message": comp["why"], "safety_checked": True}

# --- C6 Fit (single exact product + need) ---
if r.intent == router.INTENT_EXACT_LOOKUP and selected_products:
    prof = prior_profile or {}
    fit = ev.evaluate_fit(selected_products[0], budget_max=prof.get("budget_max"),
                          area_m2=prof.get("area_m2"))
    return {"query": text, "mode": "fit", "evaluation": fit,
            "message": _advise_from_fit(fit), "safety_checked": True}

# --- else: recommendation path (existing advise flow, with ranker + abstract rerank) ---
```

## Two hooks in the existing recommendation path

1. **Ranker by category** — `advise()`/`rank_top` is aircon. Route phones to `phone_ranking.rank_phones`:
   ```python
   if r.ranker == "phone":
       items = phone_ranking.rank_phones(phone_need_from(profile), records, n)
   else:
       ... existing rank_top ...
   ```
   (`records` for phones = raw DMX "Điện thoại" dicts / `search_products` output.)

2. **Abstract-need rerank** — front-load the soft lifestyle need so bge ranks by it:
   ```python
   rerank_q = cmp.priority_rerank_query(text, text)   # "cho trẻ em" -> an toàn/êm first
   base["items"] = _rerank_items(rerank_q, pool_items, n, timeout)
   ```

## Accessory cross-sell (post-selection)

When the response has items (or a selected product), attach grounded accessories:
```python
from antigravity.accessory import suggest_accessories
base["accessories"] = suggest_accessories(chosen_product, accessory_pool, per_category=2)  # [] if none
```

## Requery wrap (optional, latency-permitting)

- Pass 1: `requery.rewrite_inbound(text)` before Router/NLU (cleaner intent).
- Pass 2: `requery.naturalize_response(text, base["items"], user_terms=..., fallback_message=base["message"])`
  to humanize — but this is a 2nd/3rd LLM call; skip under the <5s SLA and reuse `explanation`.

## Guardrails preserved (do not regress)

- Numbers only from engines (never LLM). `no_stock_claims`, `grounded_explanation`,
  `accessory_suggestion`, scope, clarification budget — all still apply.
- compare/fit/compat/upgrade → always append an Advise conclusion (C7 invariant).
- Recovery: 0 candidates → `no_results_terminal` message (never fabricate).
- Missing data anywhere → say "chưa có dữ liệu", never guess.

## Latency budget

1 turn = Router (0ms) + NLU extract (~0.6s) + rank (~3ms) + optional rerank (bge ~0.3s) +
optional explain (Call B ~2.6s). Keep ≤ 1 heavy LLM call on the hot path; teach/compare/fit
are code-only (fast). Requery Pass 2 only when latency allows.
