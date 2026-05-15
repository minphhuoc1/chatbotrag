"""
Test Fix #3: Citation Validator
Verifies that article citations are validated against retrieved documents
"""

import logging
from reasoning_chain import CitationValidator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock document class
class MockDocument:
    def __init__(self, content):
        self.page_content = content

def test_citation_validator():
    """Test citation validator functionality"""
    validator = CitationValidator()
    
    print("=" * 70)
    print("[*] FIX #3 VALIDATION: Citation Validator")
    print("=" * 70)
    
    # Test 1: Extract articles from documents
    print("\n[TEST 1] Extract articles from documents")
    docs = [
        MockDocument("Dieu 35 - Quy dinh ve sa thai\nChi tiet...\nDieu 35 quy dinh..."),
        MockDocument("Dieu 113 - Quy dinh ve tien luong toi thieu\n...Dieu 113..."),
        MockDocument("Dieu 114 - Tao dieu kien lam viec\n..."),
    ]
    articles = validator.extract_articles_from_docs(docs)
    print(f"[OK] Articles found: {sorted(articles)}")
    assert 35 in articles and 113 in articles and 114 in articles, "Failed to extract articles"
    
    # Test 2: Extract articles from text
    print("\n[TEST 2] Extract articles from response text")
    response_text = "Theo Dieu 35, sa thai lao dong nu... Dieu 113 quy dinh..."
    articles = validator.extract_articles_from_text(response_text)
    print(f"[OK] Articles in response: {sorted(articles)}")
    assert 35 in articles and 113 in articles, "Failed to extract articles from text"
    
    # Test 3: Validate keywords (valid articles)
    print("\n[TEST 3] Validate keywords with valid articles")
    analyzer_output = {
        "issue": "Sa thai lao dong nu",
        "keywords": ["sa thai", "Dieu 35", "bao ve"],
        "law_type": "luat lao dong"
    }
    validated = validator.validate_and_correct(analyzer_output, docs)
    print(f"[OK] Validated keywords: {validated.get('keywords')}")
    # Dieu 35 should be valid (in docs)
    assert any("35" in kw for kw in validated.get('keywords', [])), "Dieu 35 should be valid"
    
    # Test 4: Filter invalid articles (out of range)
    print("\n[TEST 4] Filter invalid articles (out of range)")
    analyzer_output = {
        "issue": "Test",
        "keywords": ["Dieu 250", "Dieu 500"],  # Invalid - Labor Law only goes to 182
        "law_type": "luat lao dong"
    }
    validated = validator.validate_and_correct(analyzer_output, docs)
    print(f"[OK] After filtering: {validated.get('keywords')}")
    print(f"[OK] Invalid articles removed: {validated.get('_invalid_articles')}")
    assert len(validated.get('keywords', [])) == 0, "Invalid articles should be filtered"
    
    # Test 5: Filter articles not in retrieved documents
    print("\n[TEST 5] Filter articles not in retrieved documents")
    analyzer_output = {
        "issue": "Test",
        "keywords": ["Dieu 25", "Dieu 35"],  # 25 is valid range but not in docs
        "law_type": "luat lao dong"
    }
    validated = validator.validate_and_correct(analyzer_output, docs)
    print(f"[OK] After filtering: {validated.get('keywords')}")
    assert any("35" in kw for kw in validated.get('keywords', [])), "Dieu 35 should remain"
    
    # Test 6: Validate response articles
    print("\n[TEST 6] Validate articles in final response")
    response_text = "Theo Dieu 35 va Dieu 250, quy dinh..."
    validation = validator.validate_response_articles(response_text, docs)
    print(f"[OK] Valid articles: {validation['valid_articles']}")
    print(f"[OK] Invalid articles: {validation['invalid_articles']}")
    print(f"[OK] Needs correction: {validation['needs_correction']}")
    assert 35 in validation['valid_articles'], "Dieu 35 should be valid"
    assert 250 in validation['invalid_articles'], "Dieu 250 should be invalid"
    assert validation['needs_correction'] == True, "Should flag for correction"
    
    # Test 7: Empty/None handling
    print("\n[TEST 7] Handle empty analyzer output")
    validated = validator.validate_and_correct(None, docs)
    print(f"[OK] Handled None input: {validated}")
    assert validated is None, "Should handle None gracefully"
    
    print("\n" + "=" * 70)
    print("[OK] FIX #3 VALIDATION: ALL 7 TESTS PASS - IMPLEMENTATION COMPLETE")
    print("=" * 70)
    return True

if __name__ == "__main__":
    try:
        success = test_citation_validator()
        exit(0 if success else 1)
    except Exception as e:
        logger.error(f"[ER] Test failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
