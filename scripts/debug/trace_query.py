#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys, json, re, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_ollama import ChatOllama
from reasoning_chain import LegalReasoningEngine
from intent import classify_intent
from src.legal_chatbot.config import ANSWER_PROMPT_PATH, DB_PATH, EMBED_MODEL, LLM_MODEL

# Use output redirection to avoid encoding issues
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

QUERY = """tôi mới tốt nghiệp cấp 2, đi làm quán nhậu từ 10h sáng đến 10h đêm có khi đến 11h đêm mới về, chủ trả lương 1 tháng 3tr5 bao cơm 2 cữ, tiền tip tự giữ có lương tháng thứ 13. Tất cả chỉ là nói miệng từ chủ không có hợp đồng lao động. Tôi làm được 20 ngày và xin ứng lương nhưng chỉ được ứng 400k. Nếu bây giờ tôi quyết định nghỉ ngang tôi có đòi được hết số lương hoặc chủ có phải đền bù gì cho tôi không vì công việc quá nặng nhọc."""

print("\n[1] INTENT CLASSIFICATION")
intent_result = classify_intent(QUERY)
print(f"Intent: {intent_result.intent} (source: {intent_result.source})")

print("\n[2] LOADING RESOURCES")
embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
vector_db = Chroma(collection_name="legal_chunks", embedding_function=embeddings, persist_directory=DB_PATH)
llm_extract = ChatOllama(model=LLM_MODEL, format="json", temperature=0.1)
llm_reason = ChatOllama(model=LLM_MODEL, temperature=0.1)
with open(ANSWER_PROMPT_PATH, encoding="utf-8") as f:
    system_prompt = f.read()
engine = LegalReasoningEngine(retriever=vector_db.as_retriever(search_kwargs={"k": 6}), 
                              llm_extract=llm_extract, llm_reason=llm_reason, system_prompt=system_prompt)
print("All resources loaded OK")

print("\n[3] ANALYZER OUTPUT")
start = time.time()
analyzer_response = engine.analyzer_chain.invoke({"input": QUERY, "chat_history": []})
print(f"Time: {time.time()-start:.2f}s")
print(f"Issue: {analyzer_response.get('issue', 'N/A')}")
keywords = analyzer_response.get("keywords", [])
print(f"Keywords: {keywords}")

print("\n[4] RETRIEVAL TRACE")
print("Query keywords: " + str(keywords))

top_6_all = []
for keyword in keywords:
    print(f"  Searching '{keyword}'...")
    results = vector_db.similarity_search_with_score(keyword, k=6)
    top_6_all.extend(results)

seen = set()
top_6 = []
for doc, score in sorted(top_6_all, key=lambda x: -x[1]):
    key = (doc.metadata.get("dieu_so"), doc.metadata.get("page"))
    if key not in seen and len(top_6) < 6:
        seen.add(key)
        top_6.append((doc, score))

print(f"\nTop 6 Retrieved Documents:")
for i, (doc, score) in enumerate(top_6, 1):
    dieu = doc.metadata.get("dieu_so", "?")
    page = doc.metadata.get("page", "?")
    print(f"  [{i}] Dieu {dieu} | Page {page} | Score {score:.4f}")

print("\n[5] GUARDRAIL CHECKS")
has_underage = any(kw in QUERY for kw in ["tốt nghiệp cấp 2", "cấp 2"])
has_hours = "10h sáng đến 10h đêm" in QUERY
has_no_contract = "không có hợp đồng" in QUERY
has_underpay = "ứng lương" in QUERY

print(f"  Mentions underage (capped 2): {has_underage} -> Should query Dieu 147-149")
print(f"  Mentions excessive hours: {has_hours} -> Should query Dieu 95, 116-118")
print(f"  No written contract: {has_no_contract} -> Should query Dieu 24-28")
print(f"  Wage/payment issues: {has_underpay} -> Should query Dieu 94, 140")

print("\n[6] EXPECTED vs RETRIEVED")
expected = ["147", "149", "95", "116", "117", "118", "24", "25", "26", "27", "28", "94", "140"]
retrieved = set()
for doc, _ in top_6:
    dieu = doc.metadata.get("dieu_so", "?")
    if dieu != "?":
        retrieved.add(dieu)

print(f"Expected Dieu: {expected}")
print(f"Retrieved Dieu: {sorted([int(d) for d in retrieved])}")
missing = set(expected) - retrieved
print(f"MISSING: {missing if missing else 'None'}")

print("\n[7] ANALYSIS")
print("Root causes for poor response:")
print("  1. Analyzer extracted 'gioi han tuoi' but retriever not finding child labor Dieu")
print("  2. MiniLM embedding weak on Vietnamese legal semantics")
print("  3. No rule-based guardrail for child labor case detection")
print("  4. System prompt has 5-group rules but none specifically address under-age workers")

print("\nFull output saved to stdout")
