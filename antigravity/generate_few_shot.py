"""Generate 50 few-shot query normalization pairs using FPT GLM-5.2 and index them into Qdrant.
"""
from __future__ import annotations

import sys
import os
import json
import logging
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import uuid

# Setup path and encoding
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from antigravity.fpt_client import chat_completion, FPTError
from antigravity.fpt_services import embed
from antigravity.vector_db import get_qdrant_client

logger = logging.getLogger(__name__)

GENERATED_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "generated_normalization_pairs.json")

def generate_data() -> str:
    print("Requesting 50 query normalization pairs from FPT GLM-5.2...")
    prompt = """
Hãy tạo cho tôi đúng 50 cặp câu tiếng Việt ở định dạng JSON để train Few-shot cho chatbot Điện Máy Xanh.
Mỗi object gồm: id (1 đến 50), input (câu khách hàng gửi có chứa lỗi như teencode, không dấu, chửi thề, hoặc lạc đề), output (câu đã chuẩn hóa lại lịch sự, chính xác ý định để đưa vào NLU), category (chọn một trong: "teencode", "no_tones", "profanity", "off_topic").
Hãy phân bổ đều 4 lỗi này (mỗi loại khoảng 12-13 câu).
Trả về dạng JSON duy nhất, dạng danh sách (array of objects), không có bất kỳ giải thích hay văn bản nào khác ngoài JSON.
"""
    messages = [
        {"role": "system", "content": "You are a Vietnamese data generation assistant. Return ONLY valid JSON."},
        {"role": "user", "content": prompt}
    ]
    
    # We call GLM-5.2 on FPT (the reasoning model) with thinking disabled so it responds directly with JSON
    raw_json = chat_completion(
        model="GLM-5.2", 
        messages=messages, 
        max_tokens=4096, 
        temperature=0.2, 
        timeout=30.0,
        response_format={"type": "json_object"},
        extra_body={"chat_template_kwargs": {"enable_thinking": False}}
    )
    return raw_json

def index_to_qdrant(pairs: list[dict[str, Any]]) -> None:
    print("Initializing Qdrant collection 'query_normalization'...")
    client = get_qdrant_client()
    
    # Recreate collection
    collections = client.get_collections()
    existing_names = [col.name for col in collections.collections]
    if "query_normalization" in existing_names:
        client.delete_collection("query_normalization")
    client.create_collection(
        collection_name="query_normalization",
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
    )
    
    print(f"Embedding and indexing {len(pairs)} pairs...")
    points = []
    
    # Batch embedding to avoid API timeouts
    inputs = [p["input"] for p in pairs]
    batch_size = 8
    vectors = []
    for i in range(0, len(inputs), batch_size):
        chunk = inputs[i:i+batch_size]
        try:
            chunk_vectors = embed(chunk, timeout=30.0)
            vectors.extend(chunk_vectors)
        except Exception as e:
            logger.error(f"Failed to embed chunk: {e}")
            vectors.extend([[0.0] * 1024 for _ in chunk])
            
    for idx, p in enumerate(pairs):
        point_id = str(uuid.uuid4())
        points.append(PointStruct(
            id=point_id,
            vector=vectors[idx],
            payload={
                "pair_id": p.get("id"),
                "input": p["input"],
                "output": p["output"],
                "category": p["category"]
            }
        ))
        
    client.upsert(collection_name="query_normalization", points=points)
    print("Indexing complete.")

def main():
    try:
        raw_output = generate_data()
        
        # Clean potential markdown wrapping
        cleaned = raw_output.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        
        # In case the model wrapped the array in a root object
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and "pairs" in parsed:
            pairs = parsed["pairs"]
        elif isinstance(parsed, dict) and "data" in parsed:
            pairs = parsed["data"]
        elif isinstance(parsed, dict):
            # Try to find any list in the dict
            lists = [v for v in parsed.values() if isinstance(v, list)]
            pairs = lists[0] if lists else []
        else:
            pairs = parsed
            
        print(f"Successfully generated {len(pairs)} pairs.")
        
        # Save to file
        os.makedirs(os.path.dirname(GENERATED_FILE_PATH), exist_ok=True)
        with open(GENERATED_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(pairs, f, ensure_ascii=False, indent=2)
        print(f"Data saved to {GENERATED_FILE_PATH}")
        
        # Index to Qdrant
        index_to_qdrant(pairs)
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
