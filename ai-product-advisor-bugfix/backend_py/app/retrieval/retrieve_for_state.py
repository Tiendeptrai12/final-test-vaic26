from __future__ import annotations

from app.catalog.catalog_store import get_catalog
from app.conversation.missing_slots import compute_missing_slots
from app.conversation.state import ConversationState
from app.retrieval.filter_products import FilterResult, filter_products


def retrieve_for_state(state: ConversationState, catalog_override: dict | None = None) -> FilterResult:
    missing_slots = compute_missing_slots(state)
    if missing_slots:
        return FilterResult(status="not_ready", missing_slots=missing_slots)

    catalog = catalog_override if catalog_override is not None else get_catalog()
    products = catalog.get(state.category, [])
    return filter_products(state.category, state.slots, products)
