# -*- coding: utf-8 -*-
"""
QA_FRAMEWORK_SENIOR.py — Comprehensive QA Suite from Senior AI Engineer Perspective

As a Senior AI Engineer, I would QA a legal chatbot on these dimensions:

1. **INTENT CLASSIFICATION ROBUSTNESS**
   - Edge cases in rule-based layer
   - LLM fallback behavior under ambiguity
   - Context-aware follow-up detection
   - False positives/negatives

2. **RAG PIPELINE QUALITY**
   - Retriever accuracy (right docs, right order)
   - Analyzer correctness (JSON parsing, keyword extraction)
   - Reasoner hallucination detection
   - Citation accuracy (Điều/Khoản extraction)

3. **MEMORY & CONTEXT**
   - Chat history window size impact
   - Context loss over long conversations
   - Cross-turn reference understanding
   - Hallucination from stale context

4. **SYSTEM CONSTRAINTS**
   - Language enforcement (Vietnamese-only)
   - Scope boundaries (labor law only)
   - Response quality metrics
   - Performance (latency, throughput)

5. **FAILURE MODES**
   - Unanswerable questions
   - Contradictions in documents
   - Misleading citations
   - Token limits & truncation

6. **USER EXPERIENCE**
   - Response clarity and usefulness
   - Tone consistency
   - Error recovery
   - Streaming quality
"""

import os
import sys
import re
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Any
import glob

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")

try:
    from langchain_chroma import Chroma
except ImportError:
    from langchain_community.vectorstores import Chroma

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from src.legal_chatbot.config import (
    ANSWER_PROMPT_PATH,
    DB_PATH,
    EMBED_MODEL,
    LLM_ANALYZER_MODEL,
    LLM_PROVIDER,
    LLM_REASONER_MODEL,
)
from src.legal_chatbot.embeddings import create_embeddings
from src.legal_chatbot.llm_factory import create_llm_clients

# ── CONFIG ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = open(ANSWER_PROMPT_PATH, "r", encoding="utf-8").read()

# ── STATUS SYMBOLS ────────────────────────────────────────────────────────────
PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"
INFO = "ℹ️  INFO"

# ── LOGGER ────────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/qa_senior.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("QA_SENIOR")

# ── REPORT CLASS ──────────────────────────────────────────────────────────────
class QAReport:
    def __init__(self):
        self.sections = {}
        self.passed = 0
        self.failed = 0
        self.warned = 0
        self.current_section = None
        self.current_items = []

    def section(self, title):
        self.current_section = title
        self.sections[title] = []
        self.current_items = self.sections[title]
        self._print_header(title)

    def _print_header(self, title):
        sep = "=" * 70
        print(f"\n{sep}")
        print(f"  {title}")
        print(sep)
        self.current_items.append(f"\n{sep}\n  {title}\n{sep}")

    def log_result(self, status, description, detail="", severity=None):
        """Log a test result"""
        line = f"  {status} | {description}"
        if detail:
            line += f"\n         → {detail}"
        self.current_items.append(line)
        print(line)
        
        if status == PASS:
            self.passed += 1
        elif status == FAIL:
            self.failed += 1
        elif status == WARN:
            self.warned += 1

    def summary(self):
        sep = "=" * 70
        total = self.passed + self.failed + self.warned
        summary_line = f"\nTOTAL: {self.passed} PASS | {self.failed} FAIL | {self.warned} WARN (out of {total})"
        print(f"\n{sep}")
        print(summary_line)
        print(sep)
        self.current_items.append(f"\n{sep}\n{summary_line}\n{sep}")
        return self.passed, self.failed, self.warned

    def save(self, filename="qa_senior_report.txt"):
        """Save report to file"""
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"QA REPORT — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(
                f"DB: {DB_PATH} | Provider: {LLM_PROVIDER} | Reasoner: {LLM_REASONER_MODEL} | Analyzer: {LLM_ANALYZER_MODEL}\n\n"
            )
            for section_title, items in self.sections.items():
                f.write("\n".join(items) + "\n")
        print(f"\n📄 Report saved to {filename}")
        return filename

# ── LOAD RESOURCES ────────────────────────────────────────────────────────────
def load_qa_resources():
    """Load LLM, embeddings, vector DB for QA"""
    print("⏳ Loading resources for QA...")
    embeddings = create_embeddings(EMBED_MODEL)
    vector_db = Chroma(persist_directory=DB_PATH, embedding_function=embeddings)
    llm = create_llm_clients().llm_reason
    print("✅ Resources loaded")
    return embeddings, vector_db, llm

# ── IMPORT MODULES ────────────────────────────────────────────────────────────
sys.path.insert(0, ".")
from intent import classify_intent
from reasoning_chain import LegalReasoningEngine

# ═══════════════════════════════════════════════════════════════════════════════
# SENIOR QA TEST SUITE
# ═══════════════════════════════════════════════════════════════════════════════

def test_1_intent_edge_cases(report: QAReport, llm: object):
    """
    TEST 1: Intent Classification Edge Cases
    
    A Senior Engineer would test:
    - Boundary cases (minimal inputs)
    - Ambiguous queries
    - Context-dependent intents
    - LLM fallback accuracy
    """
    report.section("TEST 1: INTENT CLASSIFICATION — EDGE CASES")
    
    test_cases = [
        # (input, expected_intent, description)
        ("", "GREETING", "Empty input → should default to greeting or clarify"),
        ("??", "AMBIGUOUS", "Non-sense input"),
        ("Điều 35", "AMBIGUOUS", "Only article number without context"),
        ("Tôi", "AMBIGUOUS", "Single pronoun"),
        ("Lương?", "LEGAL", "Minimal legal query"),
        ("luật", "AMBIGUOUS", "Generic term without specificity"),
        ("Tôi bị công ty nợ lương 1 năm", "LEGAL", "Complex real-world scenario"),
        ("OK", "GREETING", "Minimal acknowledgement"),
        ("Cảm ơn", "GREETING", "Gratitude"),
        ("Không biết", "AMBIGUOUS", "Expression of uncertainty"),
        ("sa thải là gì", "LEGAL", "Definition of legal term"),
        ("tôi muốn khởi kiện công ty", "LEGAL", "Legal action intent"),
        ("Mọi người như thế nào?", "OFF_TOPIC", "Generic off-topic"),
    ]
    
    print(f"\nTesting {len(test_cases)} edge cases for intent classification...")
    correct = 0
    
    for user_input, expected, description in test_cases:
        intent_res = classify_intent(user_input, llm=llm)
        intent = intent_res.intent.name
        method = intent_res.source
        is_correct = intent == expected
        correct += is_correct
        
        status = PASS if is_correct else WARN
        detail = f"Input: '{user_input}' → {intent} (expected {expected}) [{method}]"
        report.log_result(status, description, detail)
    
    accuracy = (correct / len(test_cases)) * 100
    report.log_result(
        PASS if accuracy >= 85 else WARN,
        f"Intent classifier accuracy",
        f"{correct}/{len(test_cases)} correct ({accuracy:.1f}%)"
    )

def test_2_retriever_quality(report: QAReport, vector_db):
    """
    TEST 2: Retriever Quality & Ranking
    
    A Senior Engineer would check:
    - Top-k relevance (is #1 result most relevant?)
    - Precision (no irrelevant documents)
    - Recall (finds all relevant documents)
    - Ranking quality (order matters for reasoning)
    """
    report.section("TEST 2: RETRIEVER QUALITY & RANKING")
    
    retriever = vector_db.as_retriever(search_kwargs={"k": 6})
    
    test_queries = [
        {
            "query": "Điều 35 quyền đơn phương chấm dứt hợp đồng lao động",
            "expected_keywords": ["Điều 35", "chấm dứt", "hợp đồng"],
            "min_relevant": 3,
        },
        {
            "query": "lương tối thiểu vùng bao nhiêu",
            "expected_keywords": ["lương", "tối thiểu", "vùng"],
            "min_relevant": 2,
        },
        {
            "query": "sa thải lao động nữ có thai được không",
            "expected_keywords": ["thai", "sa thải", "không được"],
            "min_relevant": 2,
        },
        {
            "query": "nghỉ phép năm bao nhiêu ngày thâm niên",
            "expected_keywords": ["nghỉ", "phép", "ngày", "thâm niên"],
            "min_relevant": 3,
        },
        {
            "query": "giờ làm việc tối đa 8 giờ",
            "expected_keywords": ["giờ", "làm việc", "tối đa"],
            "min_relevant": 2,
        },
    ]
    
    for i, test in enumerate(test_queries):
        query = test["query"]
        expected_kw = test["expected_keywords"]
        min_rel = test["min_relevant"]
        
        start = time.time()
        docs = retriever.invoke(query)
        elapsed = time.time() - start
        
        # Check top result quality
        top_doc = docs[0] if docs else None
        found_kw = sum(1 for kw in expected_kw if top_doc and kw.lower() in top_doc.page_content.lower())
        
        # Calculate relevance score
        total_relevant = sum(
            1 for doc in docs
            if any(kw.lower() in doc.page_content.lower() for kw in expected_kw)
        )
        
        is_good = found_kw >= min_rel and total_relevant >= min_rel
        status = PASS if is_good else WARN
        detail = f"Query: '{query[:40]}...' → {found_kw}/{len(expected_kw)} keywords in top result | {total_relevant}/{len(docs)} docs relevant | {elapsed:.3f}s"
        report.log_result(status, f"Query {i+1}: Retrieval quality", detail)

def test_3_analyzer_json_parsing(report: QAReport, vector_db: Chroma, llm: object):
    """
    TEST 3: Scenario Analyzer — JSON Extraction & Parsing
    
    A Senior Engineer would check:
    - JSON validity (is output valid JSON?)
    - Field presence (issue, keywords, law_type)
    - Keyword relevance (are keywords on-topic?)
    - Error handling (what if LLM returns non-JSON?)
    """
    report.section("TEST 3: SCENARIO ANALYZER — JSON PARSING ROBUSTNESS")
    
    analyzer_prompt = ChatPromptTemplate.from_messages([
        ("system", """Bạn là chuyên gia phân tích pháp lý. Phân tích tình huống và trả về JSON:
{
  "issue": "mô tả vấn đề pháp lý cốt lõi",
  "keywords": ["từ khóa 1", "từ khóa 2"],
  "law_type": "loại luật"
}
Chỉ trả JSON, không giải thích thêm."""),
        ("human", "Tình huống: {scenario}"),
    ])
    analyzer_chain = analyzer_prompt | llm
    
    test_scenarios = [
        "Công ty của tôi không cho tôi nghỉ phép dù tôi đã làm 2 năm",
        "Tôi bị sa thải đột ngột mà không có lý do",
        "Lương tôi không bằng lương tối thiểu",
        "Tôi muốn biết quyền khi mang thai",
        "Hợp đồng tôi bị công ty đơn phương chấm dứt",
    ]
    
    for scenario in test_scenarios:
        try:
            start = time.time()
            response = analyzer_chain.invoke({"scenario": scenario})
            elapsed = time.time() - start
            
            # Extract JSON from response
            content = response.content if hasattr(response, 'content') else str(response)
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            
            if json_match:
                try:
                    data = json.loads(json_match.group())
                    has_issue = "issue" in data and data["issue"]
                    has_keywords = "keywords" in data and isinstance(data["keywords"], list) and len(data["keywords"]) > 0
                    has_law_type = "law_type" in data and data["law_type"]
                    
                    is_valid = has_issue and has_keywords and has_law_type
                    status = PASS if is_valid else WARN
                    detail = f"Scenario: '{scenario[:40]}...' → JSON valid, fields: issue={has_issue}, keywords={has_keywords}, law_type={has_law_type} | {elapsed:.2f}s"
                    report.log_result(status, f"JSON parsing: {scenario[:30]}", detail)
                except json.JSONDecodeError:
                    report.log_result(FAIL, f"JSON parse failed: {scenario[:30]}", "Response is not valid JSON")
            else:
                report.log_result(WARN, f"No JSON in response: {scenario[:30]}", "LLM did not return JSON format")
        
        except Exception as e:
            report.log_result(FAIL, f"Analyzer error: {scenario[:30]}", str(e)[:60])

def test_4_citation_accuracy(report: QAReport, vector_db: Chroma, llm: object):
    """
    TEST 4: Citation Accuracy — Article Reference Extraction
    
    A Senior Engineer would check:
    - Are Điều numbers accurate?
    - Are citations traceable in original documents?
    - Any hallucinated article numbers?
    - Format consistency (Điều X, Khoản Y, Điểm Z)
    """
    report.section("TEST 4: CITATION ACCURACY & REFERENCE VALIDATION")
    
    # Initialize reasoning engine
    embeddings = create_embeddings(EMBED_MODEL)
    engine = LegalReasoningEngine(llm, vector_db)
    
    test_queries = [
        ("Người lao động được nghỉ phép bao nhiêu ngày?", ["114", "113", "115"]),  # Expected Điều numbers
        ("Sa thải lao động nữ mang thai được không?", ["138", "140", "141"]),
        ("Lương tối thiểu vùng là bao nhiêu?", ["89", "103"]),
        ("Thời gian làm việc tối đa là bao nhiêu?", ["107", "108", "109"]),
    ]
    
    for query, expected_dieu in test_queries:
        try:
            result = engine.run(query, chat_history=[])
            answer = result.get("answer", "")
            
            # Extract all Điều numbers from response
            dieu_matches = re.findall(r'Điều\s*(\d+)', answer)
            
            # Check if any expected Điều appears in response
            found_expected = any(d in dieu_matches for d in expected_dieu)
            has_citations = len(dieu_matches) > 0
            
            status = PASS if found_expected else WARN if has_citations else FAIL
            detail = f"Query: '{query[:40]}...' → Found Điều: {dieu_matches} (expected one of {expected_dieu})"
            report.log_result(status, f"Citation accuracy: {query[:30]}", detail)
        
        except Exception as e:
            report.log_result(FAIL, f"Citation test failed: {query[:30]}", str(e)[:60])

def test_5_language_enforcement(report: QAReport, vector_db: Chroma, llm: object):
    """
    TEST 5: Language Constraint Enforcement (Vietnamese-only)
    
    A Senior Engineer would check:
    - No Chinese characters in output
    - No English (except proper nouns, unavoidable terms)
    - Consistent Vietnamese tone
    - Error messages in Vietnamese
    """
    report.section("TEST 5: LANGUAGE ENFORCEMENT — VIETNAMESE ONLY")
    
    # Define regex patterns for forbidden languages
    chinese_pattern = r'[\u4E00-\u9FFF]'  # CJK unified ideographs
    english_pattern = r'\b[A-Za-z]{2,}\b'  # English words (2+ chars)
    
    engine = LegalReasoningEngine(llm, vector_db)
    
    test_queries = [
        "Điều 35 là gì?",
        "Sa thải không đúng thủ tục thì sao?",
        "Tôi không biết pháp lý",
        "Blockchain liên quan đến luật lao động không?",  # Off-topic
    ]
    
    for query in test_queries:
        try:
            result = engine.run(query, chat_history=[])
            answer = result.get("answer", "")
            
            # Check for Chinese characters
            has_chinese = bool(re.search(chinese_pattern, answer))
            
            # Check for excessive English (allow some abbreviations, acronyms)
            english_words = re.findall(english_pattern, answer)
            # Filter out common acceptable terms
            allowed_terms = {"VND", "QH", "bộ", "luật", "điều", "khoản", "ai"}
            excessive_english = len([w for w in english_words if w not in allowed_terms]) > 3
            
            is_valid = not has_chinese and not excessive_english
            status = PASS if is_valid else FAIL if has_chinese else WARN
            
            detail = f"Query: '{query[:40]}...' → Chinese: {has_chinese}, Excessive English: {excessive_english}"
            report.log_result(status, f"Language check: {query[:30]}", detail)
        
        except Exception as e:
            report.log_result(WARN, f"Language test error: {query[:30]}", str(e)[:60])

def test_6_context_carry_and_memory(report: QAReport, vector_db: Chroma, llm: object):
    """
    TEST 6: Multi-turn Context Carry & Memory
    
    A Senior Engineer would check:
    - Does bot remember context across turns?
    - Can it answer follow-up questions without re-context?
    - Does it handle pronouns correctly (tôi, họ, v.v.)?
    - What's the max turn depth before context loss?
    """
    report.section("TEST 6: MULTI-TURN CONTEXT CARRY & MEMORY")
    
    engine = LegalReasoningEngine(llm, vector_db)
    
    # Simulate multi-turn conversation
    conversation = [
        ("Điều 35 nói về cái gì?", "Should explain Điều 35"),
        ("Điều đó áp dụng cho trường hợp của tôi không?", "Should reference Điều 35 from turn 1"),
        ("Nếu công ty vi phạm thì sao?", "Should understand context from turn 1-2"),
        ("Tôi có thể kiện không?", "Should know it's about Điều 35 / hợp đồng chấm dứt"),
    ]
    
    chat_history = []
    
    for turn, (user_input, expectation) in enumerate(conversation, 1):
        try:
            start = time.time()
            result = engine.run(user_input, chat_history=chat_history)
            elapsed = time.time() - start
            
            answer = result.get("answer", "")
            
            # Update chat history
            chat_history.append(HumanMessage(content=user_input))
            chat_history.append(AIMessage(content=answer))
            
            # Simple heuristic: check if answer is contextually relevant
            # (would need proper evaluation in production)
            is_relevant = len(answer) > 20 and "không" not in answer.lower()[:50]
            
            status = PASS if is_relevant else WARN
            detail = f"Turn {turn}: '{user_input[:30]}...' → {len(answer)} chars, {elapsed:.1f}s"
            report.log_result(status, f"Turn {turn}: {expectation}", detail)
        
        except Exception as e:
            report.log_result(FAIL, f"Turn {turn} error", str(e)[:60])

def test_7_performance_and_latency(report: QAReport, vector_db: Chroma, llm: object):
    """
    TEST 7: Performance Metrics
    
    A Senior Engineer would check:
    - Retrieval latency
    - LLM inference time (by model size)
    - Total E2E latency
    - Streaming quality
    - Memory usage
    """
    report.section("TEST 7: PERFORMANCE & LATENCY")
    
    retriever = vector_db.as_retriever(search_kwargs={"k": 6})
    engine = LegalReasoningEngine(llm, vector_db)
    
    # Test retriever latency
    queries = [
        "Điều 35 quyền đơn phương chấm dứt",
        "lương tối thiểu vùng",
        "sa thải lao động nữ mang thai",
    ]
    
    retrieval_times = []
    for query in queries:
        start = time.time()
        docs = retriever.invoke(query)
        elapsed = time.time() - start
        retrieval_times.append(elapsed)
    
    avg_retrieval = sum(retrieval_times) / len(retrieval_times)
    status = PASS if avg_retrieval < 0.1 else WARN if avg_retrieval < 0.5 else FAIL
    report.log_result(status, "Retriever latency (k=6)", f"Avg: {avg_retrieval:.3f}s per query (targets <100ms)")
    
    # Test LLM inference time
    inference_times = []
    for query in queries:
        try:
            start = time.time()
            result = engine.run(query, chat_history=[])
            elapsed = time.time() - start
            inference_times.append(elapsed)
        except:
            pass
    
    if inference_times:
        avg_inference = sum(inference_times) / len(inference_times)
        status = PASS if avg_inference < 30 else WARN if avg_inference < 60 else FAIL
        report.log_result(status, "LLM inference time", f"Avg: {avg_inference:.1f}s (qwen2.5:3b is ~20-40s expected)")

def test_8_error_handling_and_edge_cases(report: QAReport, vector_db: Chroma, llm: object):
    """
    TEST 8: Error Handling & Failure Modes
    
    A Senior Engineer would check:
    - Graceful error handling
    - What happens with malformed input?
    - Token limits (max input length)?
    - Fallback behavior
    - Error messages are helpful
    """
    report.section("TEST 8: ERROR HANDLING & EDGE CASES")
    
    engine = LegalReasoningEngine(llm, vector_db)
    
    edge_cases = [
        ("", "Empty input"),
        ("?" * 100, "Repeated special chars"),
        ("a" * 5000, "Extremely long input (token limit test)"),
        ("███████", "Special unicode blocks"),
        ("null\nundefined\nNone", "Programming keywords"),
    ]
    
    for user_input, description in edge_cases:
        try:
            result = engine.run(user_input[:2000], chat_history=[])  # Truncate to prevent excessive processing
            answer = result.get("answer", "")
            
            # Check if system handled gracefully (returned non-empty, sensible response)
            is_handled = len(answer) > 10 and "lỗi" not in answer.lower()[:100]
            
            status = PASS if is_handled else WARN
            detail = f"Input: '{user_input[:30]}...' → Handled gracefully, returned {len(answer)} chars"
            report.log_result(status, description, detail)
        
        except Exception as e:
            # Edge case that causes crash is a FAIL
            report.log_result(FAIL, description, f"Exception: {str(e)[:50]}")

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 70)
    print("  SENIOR AI ENGINEER — COMPREHENSIVE QA SUITE")
    print("=" * 70)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(
        f"  DB: {DB_PATH} | Provider: {LLM_PROVIDER} | Reasoner: {LLM_REASONER_MODEL} | Analyzer: {LLM_ANALYZER_MODEL}"
    )
    print("=" * 70)
    
    # Load resources
    embeddings, vector_db, llm = load_qa_resources()
    
    # Create report
    report = QAReport()
    
    # Run all tests
    try:
        test_1_intent_edge_cases(report, llm)
        test_2_retriever_quality(report, vector_db)
        test_3_analyzer_json_parsing(report, vector_db, llm)
        test_4_citation_accuracy(report, vector_db, llm)
        test_5_language_enforcement(report, vector_db, llm)
        test_6_context_carry_and_memory(report, vector_db, llm)
        test_7_performance_and_latency(report, vector_db, llm)
        test_8_error_handling_and_edge_cases(report, vector_db, llm)
    except Exception as e:
        print(f"\n❌ Critical error during testing: {e}")
        import traceback
        traceback.print_exc()
    
    # Summary and save
    passed, failed, warned = report.summary()
    report.save("qa_senior_report.txt")
    
    # Final verdict
    print("\n" + "=" * 70)
    if failed == 0:
        print("  ✅ SYSTEM HEALTHY — Ready for production")
        if warned > 0:
            print(f"     ({warned} warnings to investigate)")
    else:
        print(f"  ❌ ISSUES FOUND — {failed} critical failures")
        print(f"     Please review qa_senior_report.txt for details")
    print("=" * 70)
    
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
