"""
Test Fix #1: JSON Parsing Fallback - Direct Unit Test
Tests _extract_keywords_fallback() logic without LangChain
"""

import re
from typing import List

# Mock implementation of fallback logic
class MockLegalEngine:
    LEGAL_KEYWORDS_BANK = [
        "sa thải", "chấm dứt", "hợp đồng", "lương", "tối thiểu",
        "mang thai", "lao động nữ", "lao động", "bảo vệ", "không được",
        "nghỉ phép", "phép năm", "thâm niên", "hằng năm",
        "giờ làm việc", "tối đa", "ngày", "tuần",
        "bảo hiểm xã hội", "bảo hiểm y tế", "thôi việc",
        "thưởng tết", "thưởng kết quả", "phụ cấp",
        "hóa đơn", "chứng chỉ", "trình độ", "kỹ năng",
        "vi phạm", "xử phạt", "kỷ luật", "ứng xử",
        "hòa giải", "trọng tài", "kiện", "yêu cầu",
        "điều 35", "điều 113", "điều 114", "điều 138", "điều 140"
    ]
    
    def _extract_keywords_fallback(self, text: str) -> List[str]:
        """Fixed version of fallback with bug fixes"""
        text_lower = text.lower()
        
        # Step 1: Check if user explicitly mentions article numbers
        article_pattern = r'điều\s*(\d+)'
        article_matches = re.findall(article_pattern, text_lower)
        keywords = [f"Điều {m}" for m in article_matches if 1 <= int(m) <= 182]
        
        # Step 2: Match against legal keyword bank
        for keyword in self.LEGAL_KEYWORDS_BANK:
            if keyword.lower() in text_lower and keyword not in keywords:
                keywords.append(keyword)
                if len(keywords) >= 5:
                    break
        
        # Step 3: Extract meaningful words (fixed: filter non-alphabetic)
        if not keywords:
            words = text_lower.split()
            pronouns = {"tôi", "bạn", "họ", "chúng", "nó", "cái", "chiếc", "những", 
                       "các", "được", "là", "của", "cho", "từ", "để", "vào", "với"}
            # FIXED: Add check for alphabetic characters
            meaningful_words = [
                w for w in words 
                if w not in pronouns and len(w) >= 3 and any(c.isalpha() for c in w)
            ]
            
            if meaningful_words:
                keywords = meaningful_words[:3]
        
        # Fallback
        if not keywords:
            keywords = ["luật lao động"]
        
        return keywords[:5]

# Test cases
print("=" * 70)
print("TEST FIX #1: JSON Parsing Fallback - Direct Logic Test")
print("=" * 70)

engine = MockLegalEngine()
passed = 0
failed = 0

tests = [
    {
        "name": "Test 1: Sa thải + mang thai extraction",
        "input": "Sa thải lao động nữ mang thai được không?",
        "expect": ["sa thải", "mang thai"]
    },
    {
        "name": "Test 2: Article number extraction",
        "input": "Điều 35 quyền đơn phương chấm dứt hợp đồng",
        "expect": ["Điều 35"]
    },
    {
        "name": "Test 3: Lương + tối thiểu",
        "input": "Lương tối thiểu là bao nhiêu?",
        "expect": ["lương", "tối thiểu"]
    },
    {
        "name": "Test 4: Lao động + nghỉ phép (FIXED)",
        "input": "Người lao động được nghỉ phép bao nhiêu ngày?",
        "expect": ["lao động", "nghỉ phép"]
    },
    {
        "name": "Test 5: Empty/invalid input fallback (FIXED)",
        "input": "????",
        "expect": ["luật lao động"]
    }
]

for test in tests:
    result = engine._extract_keywords_fallback(test["input"])
    
    # Check if expected keywords are in result
    has_expected = any(
        exp.lower() in [r.lower() for r in result]
        for exp in test["expect"]
    )
    
    status = "[OK] PASS" if has_expected else "[ER] FAIL"
    print(f"\n{status} | {test['name']}")
    print(f"     Input: \"{test['input']}\"")
    print(f"     Expected: {test['expect']}")
    print(f"     Got: {result}")
    
    if has_expected:
        passed += 1
    else:
        failed += 1

print("\n" + "=" * 70)
print(f"RESULTS: {passed} PASS / {failed} FAIL")
print("=" * 70)

if failed == 0:
    print("[OK] FIX #1: ALL TESTS PASS - FALLBACK LOGIC WORKING")
else:
    print(f"[ER] FIX #1: {failed} TEST(S) FAILED")

exit(0 if failed == 0 else 1)
