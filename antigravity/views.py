"""FastAPI routes for the AI Product Advisor API."""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from antigravity.core import ProductAdvisor

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
    """Process a Vietnamese product query and return advisory response with safety check."""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    try:
        response = advisor.query_advisor(request.query)
        return response
    except Exception as e:
        logger.exception("chat_endpoint error for query: %s", request.query[:100])
        raise HTTPException(status_code=500, detail="Internal server error")

