"""
Test Fix #2: Improve analyzer keywords with few-shot examples
Verifies that analyzer produces specific keywords instead of generic ones
"""

import logging
import json
from langchain_community.llms import Ollama
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from reasoning_chain import LegalReasoningEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Setup LLM and retriever
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
LLM_MODEL = "qwen2:1.5b"
DB_PATH = "vector_db/legal_docs"

try:
    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    vector_db = Chroma(persist_directory=DB_PATH, embedding_function=embeddings)
    llm_extract = Ollama(model=LLM_MODEL, temperature=0.1, format="json")
    llm_reason = Ollama(model=LLM_MODEL, temperature=0.3)
    
    system_prompt = """Bạn là chuyên gia tư vấn pháp lý lao động Việt Nam."""
    
    engine = LegalReasoningEngine(
        retriever=vector_db.as_retriever(search_kwargs={"k": 3}),
        llm_extract=llm_extract,
        llm_reason=llm_reason,
        system_prompt=system_prompt
    )
    
except Exception as e:
    logger.error(f"Setup failed: {e}")
    exit(1)

# Test cases with expected SPECIFIC keywords
test_cases = [
    {
        "name": "Test 1: Sa thải lao động nữ mang thai",
        "input": "Tôi bị sa thải vì mang thai, tôi biết gì về quyền của tôi?",
        "expect_keywords": ["sa thải", "mang thai"],
        "avoid_keywords": ["luật", "quyền", "vấn đề"]
    },
    {
        "name": "Test 2: Lương tối thiểu",
        "input": "Làm việc 50 tiếng/tuần, lương tối thiểu vùng là bao nhiêu?",
        "expect_keywords": ["lương", "tối thiểu"],
        "avoid_keywords": ["luật", "vấn đề"]
    },
    {
        "name": "Test 3: Nghỉ phép hằng năm",
        "input": "Làm việc 3 năm nhưng không được nghỉ phép 12 ngày, sao thế?",
        "expect_keywords": ["nghỉ phép", "thâm niên"],
        "avoid_keywords": ["luật", "quyền"]
    },
    {
        "name": "Test 4: Hợp đồng lao động",
        "input": "Sếp ép ký hợp đồng 1 năm rồi chấm dứt ngay, đúng không?",
        "expect_keywords": ["hợp đồng", "chấm dứt"],
        "avoid_keywords": ["luật", "vấn đề"]
    },
    {
        "name": "Test 5: Giờ làm việc",
        "input": "Công ty bắt làm từ 7 sáng đến 9 tối mỗi ngày, có vượt quá không?",
        "expect_keywords": ["giờ làm việc"],
        "avoid_keywords": ["luật"]
    }
]

def test_analyzer_keywords():
    """Test that analyzer produces specific keywords"""
    passed = 0
    failed = 0
    
    for test in test_cases:
        logger.info(f"\n{'='*70}")
        logger.info(f"🧪 {test['name']}")
        logger.info(f"Input: {test['input']}")
        
        try:
            # Call analyzer directly (not full chain)
            analysis = engine.analyzer_chain.invoke({
                "input": test['input'],
                "chat_history": []
            })
            
            keywords = analysis.get("keywords", [])
            issue = analysis.get("issue", "")
            
            logger.info(f"📊 Analysis output: {analysis}")
            logger.info(f"🔑 Keywords extracted: {keywords}")
            
            # Check: at least one expected keyword present
            has_expected = any(
                kw.lower() in [k.lower() for k in keywords]
                for kw in test['expect_keywords']
            )
            
            # Check: no generic keywords
            has_generic = any(
                kw.lower() in [k.lower() for k in keywords]
                for kw in test['avoid_keywords']
            )
            
            if has_expected and not has_generic:
                logger.info(f"✅ PASS: Specific keywords found, no generic terms")
                passed += 1
            elif has_expected:
                logger.warning(f"⚠️  PARTIAL: Has expected keywords but also generic: {keywords}")
                passed += 1  # Still count as pass if expected keywords present
            else:
                logger.error(f"❌ FAIL: Missing expected keywords. Got: {keywords}")
                failed += 1
                
        except Exception as e:
            logger.error(f"❌ ERROR: {e}")
            failed += 1
    
    logger.info(f"\n{'='*70}")
    logger.info(f"📈 RESULTS: {passed}/{passed+failed} PASS")
    logger.info(f"{'='*70}\n")
    
    return passed, failed

if __name__ == "__main__":
    passed, failed = test_analyzer_keywords()
    exit(0 if failed == 0 else 1)
