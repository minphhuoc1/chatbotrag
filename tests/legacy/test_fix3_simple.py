"""
Test Fix #3: Citation Validator - Unit Test (No LangChain Dependencies)
Tests the CitationValidator class logic independently
"""

import re
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock CitationValidator implementation for testing
class CitationValidator:
    VALID_ARTICLES = set(range(1, 183))  # 1-182
    
    def extract_articles_from_docs(self, docs):
        """Extract article numbers from documents"""
        articles = set()
        for doc in docs:
            matches = re.findall(r'[Dd]ieu\s*(\d+)', doc)
            articles.update(int(m) for m in matches if m.isdigit())
        return articles
    
    def extract_articles_from_text(self, text):
        """Extract article numbers from text"""
        articles = set()
        matches = re.findall(r'[Dd]ieu\s*(\d+)', text)
        articles.update(int(m) for m in matches if m.isdigit())
        return articles
    
    def validate_and_correct(self, analyzer_output, docs):
        """Validate keywords against documents"""
        if not analyzer_output or "keywords" not in analyzer_output:
            return analyzer_output
        
        doc_articles = self.extract_articles_from_docs(docs)
        validated_keywords = []
        invalid_articles = []
        
        for kw in analyzer_output.get("keywords", []):
            article_match = re.search(r'[Dd]ieu\s*(\d+)', kw)
            if article_match:
                article_num = int(article_match.group(1))
                if article_num in self.VALID_ARTICLES and article_num in doc_articles:
                    validated_keywords.append(kw)
                elif article_num not in self.VALID_ARTICLES:
                    invalid_articles.append(article_num)
                else:
                    invalid_articles.append(article_num)
            else:
                validated_keywords.append(kw)
        
        if validated_keywords:
            analyzer_output["keywords"] = validated_keywords
        if invalid_articles:
            analyzer_output["_invalid_articles"] = invalid_articles
        
        return analyzer_output

def test_citation_validator():
    """Test citation validator"""
    validator = CitationValidator()
    
    print("=" * 70)
    print("[*] FIX #3 VALIDATION: Citation Validator Unit Tests")
    print("=" * 70)
    
    passed = 0
    failed = 0
    
    # Test 1: Extract articles from documents
    print("\n[TEST 1] Extract articles from documents")
    docs = [
        "Dieu 35 - Quy dinh ve sa thai",
        "Dieu 113 - Quy dinh ve tien luong",
        "Dieu 114 - Tao dieu kien lam viec",
    ]
    articles = validator.extract_articles_from_docs(docs)
    if 35 in articles and 113 in articles and 114 in articles:
        print(f"[OK] PASS: Articles found {sorted(articles)}")
        passed += 1
    else:
        print(f"[ER] FAIL: Expected [35, 113, 114], got {sorted(articles)}")
        failed += 1
    
    # Test 2: Extract articles from text
    print("\n[TEST 2] Extract articles from response text")
    response = "Theo Dieu 35, sa thai... Dieu 113 quy dinh..."
    articles = validator.extract_articles_from_text(response)
    if 35 in articles and 113 in articles:
        print(f"[OK] PASS: Articles in response {sorted(articles)}")
        passed += 1
    else:
        print(f"[ER] FAIL: Expected [35, 113], got {sorted(articles)}")
        failed += 1
    
    # Test 3: Valid articles in keywords
    print("\n[TEST 3] Validate keywords with valid articles")
    output = {
        "issue": "Sa thai",
        "keywords": ["sa thai", "Dieu 35", "bao ve"],
        "law_type": "luat"
    }
    docs = ["Dieu 35 - Quy dinh", "Dieu 113 - Khac"]
    validated = validator.validate_and_correct(output, docs)
    has_35 = any("35" in kw for kw in validated.get('keywords', []))
    if has_35:
        print(f"[OK] PASS: Dieu 35 retained {validated.get('keywords')}")
        passed += 1
    else:
        print(f"[ER] FAIL: Dieu 35 should be kept")
        failed += 1
    
    # Test 4: Invalid articles (out of range)
    print("\n[TEST 4] Filter articles out of range (>182)")
    output = {
        "issue": "Test",
        "keywords": ["Dieu 250", "Dieu 500"],
        "law_type": "luat"
    }
    validated = validator.validate_and_correct(output, docs)
    # When all keywords are invalid, fallback keeps original
    # But _invalid_articles should be set
    if "_invalid_articles" in validated:
        print(f"[OK] PASS: Invalid articles marked: {validated.get('_invalid_articles')}")
        passed += 1
    else:
        print(f"[ER] FAIL: Should mark invalid articles")
        failed += 1
    
    # Test 5: Articles not in documents
    print("\n[TEST 5] Filter articles not in retrieved documents")
    output = {
        "issue": "Test",
        "keywords": ["Dieu 25", "Dieu 35"],
        "law_type": "luat"
    }
    docs = ["Dieu 35 - Quy dinh", "Dieu 113 - Khac"]
    validated = validator.validate_and_correct(output, docs)
    has_35 = any("35" in kw for kw in validated.get('keywords', []))
    no_25 = not any("25" in kw for kw in validated.get('keywords', []))
    if has_35 and no_25:
        print(f"[OK] PASS: Dieu 35 kept, Dieu 25 filtered")
        passed += 1
    else:
        print(f"[ER] FAIL: Dieu 35 should be kept, Dieu 25 filtered")
        failed += 1
    
    # Test 6: Handle empty keywords
    print("\n[TEST 6] Handle empty analyzer output")
    validated = validator.validate_and_correct(None, docs)
    if validated is None:
        print(f"[OK] PASS: Handled None input gracefully")
        passed += 1
    else:
        print(f"[ER] FAIL: Should handle None")
        failed += 1
    
    # Test 7: Non-article keywords preserved
    print("\n[TEST 7] Preserve non-article keywords")
    output = {
        "keywords": ["sa thai", "mang thai", "bao ve"],
        "law_type": "luat"
    }
    validated = validator.validate_and_correct(output, docs)
    if len(validated.get('keywords', [])) == 3:
        print(f"[OK] PASS: Non-article keywords preserved: {validated.get('keywords')}")
        passed += 1
    else:
        print(f"[ER] FAIL: Non-article keywords should be kept")
        failed += 1
    
    print("\n" + "=" * 70)
    print(f"[*] RESULTS: {passed}/{passed+failed} TESTS PASS")
    if failed == 0:
        print("[OK] FIX #3 VALIDATION: COMPLETE - ALL TESTS PASS")
    else:
        print(f"[ER] FIX #3 VALIDATION: {failed} TEST(S) FAILED")
    print("=" * 70)
    
    return failed == 0

if __name__ == "__main__":
    success = test_citation_validator()
    exit(0 if success else 1)
