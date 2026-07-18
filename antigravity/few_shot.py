"""Module to parse chat history and provide few-shot examples from historical dialogues.

Provides robust parsing of the malformed chat_history_buy_product.json.
"""
from __future__ import annotations

import os
import re
import json
import logging
from typing import Any
import dirtyjson

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_PATH = os.path.join(BASE_DIR, "chat_history_buy_product.json")
SAMPLE_HISTORY_PATH = os.path.join(BASE_DIR, "35sample_chat_history (1).json")

def load_and_clean_history() -> list[dict[str, Any]]:
    """Load both history files and clean them for parsing."""
    conversations = []
    
    # 1. Load chat_history_buy_product.json (malformed)
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                content = f.read()
            fixed = re.sub(r'\{\s*\{\s*"role":', '{\n    "messages": [\n      {"role":', content)
            fixed = re.sub(r'\}\s*\{\s*"role":', '},\n      {"role":', fixed)
            data = dirtyjson.loads(fixed)
            conversations.extend([dict(conv) for conv in data])
        except Exception as e:
            logger.error(f"Failed to parse chat_history_buy_product.json: {e}")
            
    # 2. Load 35sample_chat_history (1).json (clean JSON)
    if os.path.exists(SAMPLE_HISTORY_PATH):
        try:
            with open(SAMPLE_HISTORY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            conversations.extend([dict(conv) for conv in data])
        except Exception as e:
            logger.error(f"Failed to parse 35sample_chat_history (1).json: {e}")
            
    return conversations

def extract_dialogue_turns(conversations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract turns, combining consecutive user or assistant messages."""
    turns = []
    
    for conv in conversations:
        messages = conv.get("messages", [])
        msg_dicts = [dict(m) for m in messages if m is not None]
        
        # Merge consecutive messages of the same role
        merged_msgs = []
        current_msg = None
        for msg in msg_dicts:
            role = msg.get("role")
            content = msg.get("content") or ""
            if not role or not content.strip():
                continue
            
            if current_msg and current_msg["role"] == role:
                current_msg["content"] += " " + content.strip()
            else:
                if current_msg:
                    merged_msgs.append(current_msg)
                current_msg = {"role": role, "content": content.strip(), "web_url": msg.get("web_url", "")}
        if current_msg:
            merged_msgs.append(current_msg)
            
        # Build dialogue turns
        context_turns = []
        for i in range(len(merged_msgs)):
            msg = merged_msgs[i]
            role = msg["role"]
            content = msg["content"]
            
            if role == "user" and content:
                # Find the next assistant message
                assistant_reply = ""
                if i + 1 < len(merged_msgs) and merged_msgs[i + 1]["role"] == "assistant":
                    assistant_reply = merged_msgs[i + 1]["content"]
                
                if assistant_reply:
                    context_str = ""
                    if context_turns:
                        context_str = "\n".join([f"{t['role']}: {t['content']}" for t in context_turns[-3:]])
                        
                    turns.append({
                        "user_query": content,
                        "assistant_response": assistant_reply,
                        "context": context_str,
                        "web_url": msg.get("web_url", "")
                    })
                    
            context_turns.append({"role": "Khách hàng" if role == "user" else "Trợ lý", "content": content})
            
    return turns

def get_few_shot_prompt(few_shots: list[dict[str, Any]]) -> str:
    """Format a list of few-shot examples into a system prompt segment."""
    if not few_shots:
        return ""
        
    prompt = "Dưới đây là một số ví dụ tham khảo về cách tư vấn cskh của Điện Máy Xanh:\n\n"
    for idx, fs in enumerate(few_shots, 1):
        prompt += f"Ví dụ {idx}:\n"
        if fs.get("context"):
            prompt += f"Bối cảnh:\n{fs['context']}\n"
        prompt += f"Khách hàng: {fs['user_query']}\n"
        prompt += f"Trợ lý Điện Máy Xanh: {fs['assistant_response']}\n"
        prompt += "-" * 20 + "\n"
    return prompt
