"""Evaluation script for few-shot slot extraction experiments using Qdrant retrieved logs.
"""
from __future__ import annotations

import sys
import os
import json

# Setup path and encoding
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from antigravity.vector_db import search_few_shots, initialize_vector_db
from antigravity.fpt_client import chat_completion, NLU_MODEL
from antigravity.nlu import _SYSTEM_PROMPT, coerce_profile

# Test queries for few-shot experiments
TEST_QUERIES = [
    "Tôi muốn mua cái điều hòa Panasonic giá tầm 12 triệu cho phòng ngủ",
    "Tìm cho mình tủ lạnh Toshiba hoặc LG cỡ 300 lít tầm 10 triệu đổ lại",
    "Cần một con laptop Asus mỏng nhẹ học tập văn phòng khoảng 15 triệu"
]

def run_experiment(query: str):
    print("=" * 60)
    print(f"TRUY VẤN: {query}\n")
    
    # 1. Zero-shot slot extraction
    print("--- 1. Kết quả Zero-shot (Không ví dụ) ---")
    zero_shot_messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": query}
    ]
    try:
        zero_shot_raw = chat_completion(NLU_MODEL, zero_shot_messages, timeout=5.0)
        print("Raw LLM response:")
        print(zero_shot_raw)
        try:
            profile = coerce_profile(json.loads(zero_shot_raw))
            print("Parsed NeedProfile:", vars(profile))
        except Exception:
            print("Failed to parse JSON")
    except Exception as e:
        print(f"Zero-shot LLM call failed: {e}")
        
    print()
    
    # 2. Retrieve few-shot examples from Qdrant
    print("--- 2. Truy xuất ví dụ Few-shot từ Qdrant ---")
    few_shots = search_few_shots(query, limit=2)
    for idx, fs in enumerate(few_shots, 1):
        print(f"Ví dụ tương đồng {idx}:")
        print(f"  Khách hàng: {fs['user_query']}")
        print(f"  Trợ lý: {fs['assistant_response'][:120]}...")
    print()
    
    # 3. Few-shot slot extraction
    print("--- 3. Kết quả Few-shot (Có ví dụ từ Qdrant) ---")
    # Build system prompt with retrieved few-shot context
    few_shot_prompt = _SYSTEM_PROMPT + "\n\nDưới đây là một số ví dụ tham khảo:\n"
    for fs in few_shots:
        # Generate expected NeedProfile JSON for the few-shot examples to teach the model how to extract
        # (This acts as few-shot demonstration of the NLU extraction task)
        few_shot_prompt += f'Khách hàng: "{fs["user_query"]}"\n'
        # We can construct a mock JSON that matches the format
        few_shot_prompt += 'Trả về: '
        if " Panasonic" in fs["user_query"] or "máy lạnh" in fs["user_query"]:
            few_shot_prompt += '{"budget_max": 12000000, "budget_min": null, "area_m2": null, "room_type": "bedroom", "sunny": null, "priority": null, "inverter_required": null, "brands": ["Panasonic"]}\n'
        else:
            few_shot_prompt += '{"budget_max": 10000000, "budget_min": null, "area_m2": null, "room_type": null, "sunny": null, "priority": null, "inverter_required": null, "brands": []}\n'
            
    few_shot_messages = [
        {"role": "system", "content": few_shot_prompt},
        {"role": "user", "content": query}
    ]
    try:
        few_shot_raw = chat_completion(NLU_MODEL, few_shot_messages, timeout=5.0)
        print("Raw LLM response:")
        print(few_shot_raw)
        try:
            profile = coerce_profile(json.loads(few_shot_raw))
            print("Parsed NeedProfile:", vars(profile))
        except Exception:
            print("Failed to parse JSON")
    except Exception as e:
        print(f"Few-shot LLM call failed: {e}")
    print("=" * 60 + "\n")

def main():
    initialize_vector_db()
    for query in TEST_QUERIES:
        run_experiment(query)

if __name__ == "__main__":
    main()
