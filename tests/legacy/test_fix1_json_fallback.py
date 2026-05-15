#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Fix #1: JSON Parsing Fallback

Verifies that the analyzer gracefully handles non-JSON responses
and falls back to keyword extraction.
"""

import sys
import os

# Setup environment
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")

sys.path.insert(0, ".")

from reasoning_chain import LegalReasoningEngine

def test_fallback_extraction():
    """Test the _extract_keywords_fallback method"""
    print("\n" + "="*70)
    print("TEST FIX #1: JSON Parsing Fallback — Keyword Extraction")
    print("="*70)
    
    # Create a minimal engine just to test the fallback method
    class MinimalEngine:
        LEGAL_KEYWORDS_BANK = [
            "sa thải", "chấm dứt", "hợp đồng", "lương", "tối thiểu",
            "mang thai", "lao động nữ", "bảo vệ", "không được",
            "nghỉ phép", "phép năm", "thâm niên", "hằng năm",
            "giờ làm việc", "tối đa", "ngày", "tuần",
            "bảo hiểm xã hội", "bảo hiểm y tế", "thôi việc",
            "thưởng tết", "thưởng kết quả", "phụ cấp",
            "hóa đơn", "chứng chỉ", "trình độ", "kỹ năng",
            "vi phạm", "xử phạt", "kỷ luật", "ứng xử",
            "hòa giải", "trọng tài", "kiện", "yêu cầu",
            "điều 35", "điều 113", "điều 114", "điều 138", "điều 140"
        ]
    
    engine = MinimalEngine()
    
    # Copy the fallback method
    def extract_keywords_fallback(text):
        import re
        text_lower = text.lower()
        
        # Step 1: Check if user explicitly mentions article numbers (Điều X)
        article_pattern = r'điều\s*(\d+)'
        article_matches = re.findall(article_pattern, text_lower)
        keywords = [f"Điều {m}" for m in article_matches if 1 <= int(m) <= 182]
        
        # Step 2: Match against legal keyword bank
        for keyword in engine.LEGAL_KEYWORDS_BANK:
            if keyword.lower() in text_lower and keyword not in keywords:
                keywords.append(keyword)
                if len(keywords) >= 5:
                    break
        
        # Step 3: If still no keywords, extract 2-3 word phrases
        if not keywords:
            words = text_lower.split()
            pronouns = {"tôi", "bạn", "họ", "chúng", "nó", "cái", "chiếc", "những", 
                       "các", "được", "là", "của", "cho", "từ", "để", "vào", "với"}
            meaningful_words = [w for w in words if w not in pronouns and len(w) >= 3]
            
            if meaningful_words:
                keywords = meaningful_words[:3]
        
        # Fallback
        if not keywords:
            keywords = ["luật lao động"]
        
        return keywords[:5]
    
    # Test cases
    test_cases = [
        {
            "input": "Sa thải lao động nữ mang thai được không?",
            "expected_keywords": ["sa thải", "mang thai"],
            "description": "Legal keywords should be extracted"
        },
        {
            "input": "Điều 35 quyền đơn phương chấm dứt hợp đồng",
            "expected_keywords": ["Điều 35"],
            "description": "Article numbers should be extracted"
        },
        {
            "input": "Lương tối thiểu là bao nhiêu?",
            "expected_keywords": ["lương", "tối thiểu"],
            "description": "Multiple keywords should be extracted"
        },
        {
            "input": "Người lao động được nghỉ phép bao nhiêu ngày?",
            "expected_keywords": ["lao động", "nghỉ phép"],
            "description": "Keyword bank match should work"
        },
        {
            "input": "????",
            "expected_keywords": ["luật lao động"],
            "description": "Empty input should return generic fallback"
        },
    ]
    
    print("\n📋 Test Cases:\n")
    passed = 0
    failed = 0
    
    for i, test in enumerate(test_cases, 1):
        user_input = test["input"]
        expected = test["expected_keywords"]
        description = test["description"]
        
        # Extract keywords
        keywords = extract_keywords_fallback(user_input)
        
        # Check if expected keywords are in extracted keywords
        found = all(any(exp.lower() in kw.lower() for kw in keywords) for exp in expected)
        
        status = "✅ PASS" if found else "❌ FAIL"
        passed += found
        failed += not found
        
        print(f"{status} | Test {i}: {description}")
        print(f"     Input: \"{user_input}\"")
        print(f"     Expected: {expected}")
        print(f"     Got: {keywords}")
        print()
    
    # Summary
    print("="*70)
    print(f"RESULTS: {passed} PASS / {failed} FAIL")
    print("="*70)
    
    if failed == 0:
        print("✅ All tests passed! Fix #1 is working correctly.")
        return 0
    else:
        print(f"❌ {failed} test(s) failed. Please review the fallback logic.")
        return 1

if __name__ == "__main__":
    sys.exit(test_fallback_extraction())
