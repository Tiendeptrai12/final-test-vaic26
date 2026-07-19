"""FastAPI routes for the AI Product Advisor API."""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from antigravity.core import ProductAdvisor
from antigravity import btc_catalog

logger = logging.getLogger(__name__)

router = APIRouter()
advisor = ProductAdvisor()

class QueryRequest(BaseModel):
    query: str
    # multi-turn state: client resends the previous turn's `profile` so earlier slots
    # (hỏi ngược) carry forward. Server stays stateless.
    profile: dict | None = None
    # products the user referenced (for compare / fit / compatibility / upgrade), resolved
    # by the UI or vector search. Empty for the normal recommendation flow.
    selected_products: list[dict] | None = None
    # choose-factors flow: the consideration-factor ids the user picked (A/B/C/D). The
    # budget factor carries its tier as "budget:low|mid|high". Empty on the first turn.
    chosen_factors: list[str] | None = None

@router.get("/health")
async def health_check():
    """Return service health status and whether FPT API key is configured."""
    key_status = "Configured" if advisor.api_key else "Missing"
    return {
        "status": "healthy",
        "fpt_api_key": key_status
    }

class LearnRequest(BaseModel):
    user_query: str
    assistant_response: str
    context: str | None = None
    web_url: str | None = None

@router.post("/learn")
async def learn_endpoint(request: LearnRequest):
    """Add a new dialogue turn to the few_shot_chats vector DB for real-time learning."""
    if not request.user_query.strip() or not request.assistant_response.strip():
        raise HTTPException(status_code=400, detail="Query and response cannot be empty")
    try:
        from antigravity.vector_db import get_qdrant_client, FPTEmbedding
        from qdrant_client.models import PointStruct
        import uuid
        
        client = get_qdrant_client()
        embedder = FPTEmbedding()
        vector = embedder.get_text_embedding(f"Khách hàng: {request.user_query}")
        
        point_id = str(uuid.uuid4())
        client.upsert(
            collection_name="few_shot_chats",
            points=[
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "user_query": request.user_query,
                        "assistant_response": request.assistant_response,
                        "context": request.context or "",
                        "web_url": request.web_url or ""
                    }
                )
            ]
        )
        return {"status": "ok", "message": "Successfully learned new few-shot dialogue turn.", "id": point_id}
    except Exception as e:
        logger.exception("learn_endpoint error")
        raise HTTPException(status_code=500, detail=f"Failed to index new few-shot: {e}")

@router.post("/chat")
async def chat_endpoint(request: QueryRequest):
    """Process a Vietnamese product query and return advisory response.

    Real path (CATALOG_SOURCE=btc): NLU slot-extract -> code filter/rank -> grounded
    items, prices/specs straight from the catalog. Mock path (default, e.g. Vercel with
    no bundled data): static demo advisor. Gate keeps the real pipeline off environments
    that have no catalog data (NDA) while making it the default for local demo.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    try:
        if btc_catalog.is_real_catalog():
            from antigravity.nlu import build_chat_response
            return build_chat_response(request.query, prior_profile=request.profile,
                                       selected_products=request.selected_products,
                                       chosen_factors=request.chosen_factors)
        return advisor.query_advisor(request.query)
    except Exception:
        logger.exception("chat_endpoint error for query: %s", request.query[:100])
        raise HTTPException(status_code=500, detail="Internal server error")

