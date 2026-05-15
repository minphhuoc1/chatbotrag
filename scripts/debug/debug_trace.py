#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DEBUG_TRACE.py — Trace a specific query through the entire pipeline
with detailed output at each stage.
"""

import sys
import json
import logging
import re
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_ollama import ChatOllama
from reasoning_chain import LegalReasoningEngine
from intent import classify_intent
from src.legal_chatbot.config import ANSWER_PROMPT_PATH, DB_PATH, EMBED_MODEL, LLM_MODEL
import time

# ==============================================================================
# TRACE CONFIGURATION
# ==============================================================================

QUERY = """tôi mới tốt nghiệp cấp 2, đi làm quán nhậu từ 10h sáng đến 10h đêm có khi đến 11h đêm mới về, chủ trả lương 1 tháng 3tr5 bao cơm 2 cữ, tiền tip tự giữ có lương tháng thứ 13. Tất cả chỉ là nói miệng từ chủ không có hợp đồng lao động. Tôi làm được 20 ngày và xin ứng lương nhưng chỉ được ứng 400k. Nếu bây giờ tôi quyết định nghỉ ngang tôi có đòi được hết số lương hoặc chủ có phải đền bù gì cho tôi không vì công việc quá nặng nhọc."""

# ==============================================================================
# 1. INTENT CLASSIFICATION
# ==============================================================================

print("\n" + "="*80)
print("1. INTENT CLASSIFICATION")
print("="*80)

start_time = time.time()
intent_result = classify_intent(QUERY)
intent_time = time.time() - start_time

print(f"Intent: {intent_result.intent}")
print(f"Source: {intent_result.source}")
print(f"Time: {intent_time:.4f}s")
print(f"Response (if default): {intent_result.response[:100] if intent_result.response else '(none - will use RAG)'}")

if intent_result.intent != "LEGAL":
    print(f"\n⚠️ CRITICAL: Intent is '{intent_result.intent}', not LEGAL!")
    print("This query should be routed to RAG, not rejected.")
    sys.exit(1)

# ==============================================================================
# 2. LOAD RESOURCES
# ==============================================================================

print("\n" + "="*80)
print("2. LOADING RESOURCES")
print("="*80)

try:
    # Load embeddings
    print("Loading embeddings...")
    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    print(f"✓ Embeddings loaded (768 dims)")
    
    # Load vector DB
    print("Loading vector DB...")
    vector_db = Chroma(
        collection_name="legal_chunks",
        embedding_function=embeddings,
        persist_directory=DB_PATH
    )
    retriever = vector_db.as_retriever(search_kwargs={"k": 6})
    print(f"✓ Vector DB loaded with retriever (k=6)")
    
    # Load LLM
    print("Loading LLM...")
    llm_extract = ChatOllama(model=LLM_MODEL, format="json", temperature=0.1)
    llm_reason = ChatOllama(model=LLM_MODEL, temperature=0.1)
    print(f"✓ LLM loaded (qwen2.5:3b)")
    
    # Load system prompt
    print("Loading system prompt...")
    with open(ANSWER_PROMPT_PATH, encoding="utf-8") as f:
        system_prompt = f.read()
    print(f"✓ System prompt loaded ({len(system_prompt)} chars)")
    
except Exception as e:
    print(f"❌ Error loading resources: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ==============================================================================
# 3. INITIALIZE RAG ENGINE
# ==============================================================================

print("\n" + "="*80)
print("3. INITIALIZE RAG ENGINE")
print("="*80)

try:
    engine = LegalReasoningEngine(
        retriever=retriever,
        llm_extract=llm_extract,
        llm_reason=llm_reason,
        system_prompt=system_prompt
    )
    print("✓ LegalReasoningEngine initialized")
except Exception as e:
    print(f"❌ Error initializing engine: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ==============================================================================
# 4. ANALYZER OUTPUT
# ==============================================================================

print("\n" + "="*80)
print("4. ANALYZER OUTPUT")
print("="*80)

print(f"\nInput query ({len(QUERY)} chars):")
print(f"  {QUERY[:150]}...")

try:
    # Manually run analyzer to capture intermediate steps
    from langchain_core.messages import HumanMessage
    
    print(f"\n[Analyzer Prompt]")
    analyzer_chain = engine.analyzer_chain
    
    # Get the prompt template to see what's being sent
    analyzer_prompt_obj = engine.analyzer_prompt
    print(f"Prompt template messages count: {len(analyzer_prompt_obj.messages)}")
    
    # Invoke analyzer
    start_time = time.time()
    analyzer_response_raw = engine.analyzer_chain.invoke({
        "input": QUERY,
        "chat_history": []
    })
    analyzer_time = time.time() - start_time
    
    print(f"\n[Raw Analyzer Response] ({analyzer_time:.2f}s)")
    print(f"Type: {type(analyzer_response_raw)}")
    print(f"Content:\n{json.dumps(analyzer_response_raw, indent=2, ensure_ascii=False)}")
    
    # Check if fallback was used
    analyzer_keywords = analyzer_response_raw.get("keywords", [])
    print(f"\n[Parsed Keywords]")
    print(f"Keywords: {analyzer_keywords}")
    
except Exception as e:
    print(f"❌ Analyzer error: {e}")
    import traceback
    traceback.print_exc()
    # Continue anyway
    analyzer_keywords = ["lao động", "lương", "quyền lợi"]

# ==============================================================================
# 5. RETRIEVAL TRACE
# ==============================================================================

print("\n" + "="*80)
print("5. RETRIEVAL TRACE")
print("="*80)

print(f"\nRetrieval query/keywords: {analyzer_keywords}")
print(f"Top-k: 6")

try:
    start_time = time.time()
    
    # Search for each keyword and combine results
    all_results = []
    for keyword in analyzer_keywords:
        print(f"\n  Searching for: '{keyword}'")
        results = vector_db.similarity_search_with_score(keyword, k=6)  # Fixed: _with_score not _with_scores
        all_results.extend(results)
        for i, (doc, score) in enumerate(results[:3], 1):
            dieu = doc.metadata.get("dieu_so", "N/A")
            page = doc.metadata.get("page", "N/A")
            print(f"    [{i}] Điều {dieu} (page {page}) - Score: {score:.4f}")
    
    # Deduplicate and sort by score (if used)
    retrieval_time = time.time() - start_time
    
    # Get top 6 unique
    seen = set()
    top_6 = []
    for doc, score in sorted(all_results, key=lambda x: x[1], reverse=True):
        doc_id = (doc.metadata.get("dieu_so"), doc.metadata.get("page"))
        if doc_id not in seen and len(top_6) < 6:
            seen.add(doc_id)
            top_6.append((doc, score))
    
    print(f"\n[Final Top-6 Retrieved Documents] ({retrieval_time:.2f}s)")
    for i, (doc, score) in enumerate(top_6, 1):
        dieu = doc.metadata.get("dieu_so", "N/A")
        page = doc.metadata.get("page", "N/A")
        text_preview = doc.page_content[:100].replace("\n", " ")
        print(f"\n  [{i}] Điều {dieu} | Page {page} | Score: {score:.4f}")
        print(f"      Text: {text_preview}...")
    
except Exception as e:
    print(f"❌ Retrieval error: {e}")
    import traceback
    traceback.print_exc()
    top_6 = []

# ==============================================================================
# 6. RULE-BASED GUARDRAIL TRACE
# ==============================================================================

print("\n" + "="*80)
print("6. RULE-BASED GUARDRAIL TRACE")
print("="*80)

# Check for annual leave rule
print("\n[Annual Leave Rule (Fix E)]")
annual_leave_keywords = ["nghỉ phép", "phép", "hằng năm", "thâm niên"]
has_annual_leave_kw = any(kw in QUERY.lower() for kw in annual_leave_keywords)
print(f"  Matches: {has_annual_leave_kw}")
if has_annual_leave_kw:
    print(f"  → Would apply annual leave special handling")
else:
    print(f"  → Does NOT match annual leave rule")

# Check for generic article rule
print("\n[Generic Article Query Rule (Fix C)]")
generic_article_pattern = r'^\s*Điều\s*\d+\s*\??$'
is_generic = bool(re.match(generic_article_pattern, QUERY.lower().strip()))
print(f"  Matches: {is_generic}")
if is_generic:
    print(f"  → Would return clarifying question")
else:
    print(f"  → Does NOT match generic article rule")

# Check for child labor (underage worker)
print("\n[Child Labor / Underage Detection]")
underage_keywords = ["tốt nghiệp cấp 2", "cấp 2", "dưới 15", "chưa thành niên"]
has_underage = any(kw in QUERY.lower() for kw in underage_keywords)
print(f"  Mentions underage status: {has_underage}")
if has_underage:
    print(f"  ⚠️ Query mentions 'tốt nghiệp cấp 2' (completed secondary school)")
    print(f"     This implies age ~14-15 (CHILD LABOR concern!)")
    print(f"     Should trigger: Điều 147-149 (child labor protection)")
else:
    print(f"  → Does NOT mention underage/child labor indicators")

# Check working hours violation
print("\n[Working Hours Violation Detection]")
hours_keywords = ["10h sáng đến 10h đêm", "giờ làm việc", "tối đa"]
has_hours_concern = any(kw in QUERY.lower() for kw in hours_keywords)
print(f"  Mentions excessive hours: {has_hours_concern}")
if has_hours_concern:
    print(f"  ⚠️ Query mentions '10h sáng đến 10h đêm' = 12-13 hours/day")
    print(f"     This VIOLATES working hour limits (Điều 95)")
    print(f"     For minors: Even more restrictive (Điều 116-118)")
else:
    print(f"  → Does NOT mention working hours concern")

import re

# ==============================================================================
# 7. FINAL REASONING INPUT
# ==============================================================================

print("\n" + "="*80)
print("7. FINAL REASONING INPUT")
print("="*80)

# Build context from top-6
context_text = "\n\n---\n\n".join([
    f"[Điều {doc.metadata.get('dieu_so', '?')}]\n{doc.page_content}"
    for doc, _ in top_6
])

print(f"\n[System Prompt (first 300 chars)]")
print(f"  {system_prompt[:300]}...")

print(f"\n[Context from Retrieval ({len(context_text)} chars)]")
if context_text:
    print(f"  {context_text[:300]}...")
else:
    print(f"  ⚠️ No context retrieved!")

print(f"\n[Chat History]")
print(f"  (empty - first turn)")

print(f"\n[Final User Query]")
print(f"  {QUERY}")

# ==============================================================================
# 8. DRY RUN: Show what would be sent to LLM
# ==============================================================================

print("\n" + "="*80)
print("8. DRY RUN: LLM REASONING (not executing - just showing input)")
print("="*80)

print("\n[What will be sent to reasoner LLM]")
print(f"  System prompt: {len(system_prompt)} chars")
print(f"  Context docs: {len(top_6)} chunks")
print(f"  Context size: {len(context_text)} chars")
print(f"  User query: {len(QUERY)} chars")

print(f"\n⚠️ SKIPPING actual LLM reasoning to save time")
print(f"   (Run with --execute flag to get actual response)")

# ==============================================================================
# 9. EXPECTED vs ACTUAL ANALYSIS
# ==============================================================================

print("\n" + "="*80)
print("9. EXPECTED vs ACTUAL ANALYSIS")
print("="*80)

print("\n[Expected Articles for This Query]")
expected_articles = {
    "Điều 117-118": "Bảo vệ lao động nữ/người dưới 18 tuổi - cấm làm việc nặng nhọc",
    "Điều 147-149": "Bảo vệ trẻ em / người chưa thành niên (dưới 15 tuổi)",
    "Điều 95": "Thời gian làm việc tối đa (48 giờ/tuần, 8 giờ/ngày)",
    "Điều 24-28": "Hợp đồng lao động (yêu cầu viết)",
    "Điều 94": "Trả lương (đúng hạn, đủ lương)",
    "Điều 140": "Sa thải trái phép / Chấm dứt HĐ",
}

for dieu, desc in expected_articles.items():
    print(f"  ✓ {dieu}: {desc}")

print(f"\n[Actually Retrieved Articles]")
if top_6:
    retrieved_dieus = set()
    for doc, score in top_6:
        dieu = doc.metadata.get("dieu_so", "?")
        if dieu != "?":
            retrieved_dieus.add(dieu)
    print(f"  Điều: {', '.join(sorted(retrieved_dieus))}")
    
    missing = set(expected_articles.keys()) - retrieved_dieus
    if missing:
        print(f"\n  ⚠️ MISSING: {', '.join(missing)}")
else:
    print(f"  ❌ NO DOCUMENTS RETRIEVED")

print("\n" + "="*80)
print("DEBUG TRACE COMPLETE")
print("="*80)
print("\n✓ To get full LLM reasoning, run:")
print(f"  python {Path(__file__).name} --execute")
