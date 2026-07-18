"""Vector database management for catalog retrieval and few-shot dialog matching.

Integrates Qdrant with LlamaIndex using FPT's Vietnamese_Embedding model.
"""
from __future__ import annotations

import os
import json
import logging
from typing import Any, List
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from llama_index.core import VectorStoreIndex, StorageContext
from llama_index.core.schema import TextNode
from llama_index.core.embeddings import BaseEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore

from antigravity.fpt_services import embed
from antigravity.few_shot import load_and_clean_history, extract_dialogue_turns

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QDRANT_PATH = os.path.join(BASE_DIR, "qdrant_db")
PROCESSED_DATA_DIR = os.path.join(BASE_DIR, "data", "processed")

class FPTEmbedding(BaseEmbedding):
    """Custom LlamaIndex Embedding model wrapper around FPT's Vietnamese_Embedding."""
    
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        
    def _get_query_embedding(self, query: str) -> List[float]:
        try:
            vectors = embed([query], timeout=30.0)
            if vectors:
                return vectors[0]
        except Exception as e:
            logger.error(f"FPT query embedding failed: {e}")
        # Fallback to zero vector if embedding fails
        return [0.0] * 1024
        
    async def _aget_query_embedding(self, query: str) -> List[float]:
        return self._get_query_embedding(query)
        
    def _get_text_embedding(self, text: str) -> List[float]:
        try:
            vectors = embed([text], timeout=30.0)
            if vectors:
                return vectors[0]
        except Exception as e:
            logger.error(f"FPT text embedding failed: {e}")
        return [0.0] * 1024
        
    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        # Chunk into batches of 8 to avoid FPT API timeouts on large payloads
        batch_size = 8
        results = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i:i + batch_size]
            try:
                vectors = embed(chunk, timeout=30.0)
                results.extend(vectors)
            except Exception as e:
                logger.error(f"FPT batch text embedding chunk failed: {e}")
                results.extend([[0.0] * 1024 for _ in chunk])
        return results

# Initialize local Qdrant Client
_client = QdrantClient(path=QDRANT_PATH)

def get_qdrant_client() -> QdrantClient:
    return _client

def get_vector_store_index(collection_name: str) -> VectorStoreIndex:
    """Get a LlamaIndex VectorStoreIndex for a given Qdrant collection."""
    vector_store = QdrantVectorStore(client=_client, collection_name=collection_name)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    return VectorStoreIndex.from_vector_store(
        vector_store=vector_store,
        embed_model=FPTEmbedding(),
        storage_context=storage_context
    )

def format_product_for_embedding(product: dict[str, Any]) -> str:
    """Format product metadata into a rich text string for vector search."""
    name = product.get("name") or product.get("product_id") or ""
    brand = product.get("brand") or ""
    category = product.get("category") or ""
    price = product.get("price") or product.get("original_price") or 0
    spec = product.get("spec") or {}
    spec_str = ", ".join([f"{k}: {v}" for k, v in spec.items() if v is not None])
    return f"Sản phẩm: {name}. Hãng: {brand}. Ngành hàng: {category}. Giá: {price:,}đ. Thông số: {spec_str}."

def initialize_vector_db(force_reindex: bool = False) -> None:
    """Build Qdrant collections for products and few-shots if they don't exist."""
    collections = _client.get_collections()
    existing_names = [col.name for col in collections.collections]
    
    # 1. Initialize Product Catalog
    if "catalog_products" not in existing_names or force_reindex:
        logger.info("Initializing Qdrant collection 'catalog_products'...")
        # Recreate collection
        if "catalog_products" in existing_names:
            _client.delete_collection("catalog_products")
        _client.create_collection(
            collection_name="catalog_products",
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        )
        
        # Load and parse products (limit categories and counts to keep index size small/fast)
        nodes = []
        target_files = ["dmx_air_conditioner.all.jsonl", "btc_refrigerator.all.jsonl", "btc_desktop_pc.all.jsonl"]
        if os.path.exists(PROCESSED_DATA_DIR):
            for filename in target_files:
                file_path = os.path.join(PROCESSED_DATA_DIR, filename)
                if not os.path.exists(file_path):
                    continue
                try:
                    count = 0
                    with open(file_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            product = json.loads(line)
                            if product.get("data_quality", {}).get("eligible_for_demo", False):
                                text = format_product_for_embedding(product)
                                nodes.append(TextNode(
                                    text=text,
                                    metadata={"product_id": product["product_id"], "product_json": json.dumps(product)}
                                ))
                                count += 1
                                if count >= 25:
                                    break
                except Exception as e:
                    logger.error(f"Failed to load products from {filename}: {e}")
                        
        if nodes:
            logger.info(f"Indexing {len(nodes)} products into 'catalog_products'...")
            # We build index using LlamaIndex
            vector_store = QdrantVectorStore(client=_client, collection_name="catalog_products")
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            VectorStoreIndex(nodes, storage_context=storage_context, embed_model=FPTEmbedding())
            logger.info("Product catalog indexing complete.")
            
    # 2. Initialize Few-Shots
    if "few_shot_chats" not in existing_names or force_reindex:
        logger.info("Initializing Qdrant collection 'few_shot_chats'...")
        if "few_shot_chats" in existing_names:
            _client.delete_collection("few_shot_chats")
        _client.create_collection(
            collection_name="few_shot_chats",
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        )
        
        # Load, clean, and extract turns from chat history
        conversations = load_and_clean_history()
        turns = extract_dialogue_turns(conversations)
        
        nodes = []
        for turn in turns:
            text = f"Khách hàng: {turn['user_query']}"
            nodes.append(TextNode(
                text=text,
                metadata={
                    "user_query": turn["user_query"],
                    "assistant_response": turn["assistant_response"],
                    "context": turn["context"],
                    "web_url": turn["web_url"]
                }
            ))
            
        if nodes:
            logger.info(f"Indexing {len(nodes)} dialogue turns into 'few_shot_chats'...")
            vector_store = QdrantVectorStore(client=_client, collection_name="few_shot_chats")
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            VectorStoreIndex(nodes, storage_context=storage_context, embed_model=FPTEmbedding())
            logger.info("Few-shot indexing complete.")

def search_products(query: str, limit: int = 3) -> list[dict[str, Any]]:
    """Retrieve semantically matching products from the Qdrant catalog."""
    try:
        index = get_vector_store_index("catalog_products")
        retriever = index.as_retriever(similarity_top_k=limit)
        nodes = retriever.retrieve(query)
        
        results = []
        for node in nodes:
            meta = node.node.metadata
            if "product_json" in meta:
                product_data = json.loads(meta["product_json"])
                results.append(product_data)
        return results
    except Exception as e:
        logger.error(f"Catalog retrieval failed: {e}")
        return []

def search_few_shots(query: str, limit: int = 3) -> list[dict[str, Any]]:
    """Retrieve similar past dialogue turns for few-shot prompting."""
    try:
        index = get_vector_store_index("few_shot_chats")
        retriever = index.as_retriever(similarity_top_k=limit)
        nodes = retriever.retrieve(query)
        
        results = []
        for node in nodes:
            meta = node.node.metadata
            results.append({
                "user_query": meta.get("user_query", ""),
                "assistant_response": meta.get("assistant_response", ""),
                "context": meta.get("context", ""),
                "web_url": meta.get("web_url", "")
            })
        return results
    except Exception as e:
        logger.error(f"Few-shot retrieval failed: {e}")
        return []
