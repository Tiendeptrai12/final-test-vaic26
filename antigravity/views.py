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

@router.get("/health")
async def health_check():
    """Return service health status and whether FPT API key is configured."""
    key_status = "Configured" if advisor.api_key else "Missing"
    return {
        "status": "healthy",
        "fpt_api_key": key_status
    }

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
        if btc_catalog.is_btc_enabled():
            from antigravity.nlu import build_chat_response
            return build_chat_response(request.query)
        return advisor.query_advisor(request.query)
    except Exception:
        logger.exception("chat_endpoint error for query: %s", request.query[:100])
        raise HTTPException(status_code=500, detail="Internal server error")

