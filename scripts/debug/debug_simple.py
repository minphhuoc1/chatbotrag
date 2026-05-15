#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SIMPLE DEBUG TRACE - No Unicode characters, minimal dependencies
"""
import sys
import json
import re
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_ollama import ChatOllama
from reasoning_chain import LegalReasoningEngine
from intent import classify_intent
from src.legal_chatbot.config import ANSWER_PROMPT_PATH, DB_PATH, EMBED_MODEL, LLM_MODEL

QUERY = """tôi mới tốt nghiệp cấp 2, đi làm quán nhậu từ 10h sáng đến 10h đêm có khi đến 11h đêm mới về, chủ trả lương 1 tháng 3tr5 bao cơm 2 cữ, tiền tip tự giữ có lương tháng thứ 13. Tất cả chỉ là nói miệng từ chủ không có hợp đồng lao động. Tôi làm được 20 ngày và xin ứng lương nhưng chỉ được ứng 400k. Nếu bây giờ tôi quyết định nghỉ ngang tôi có đòi được hết số lương hoặc chủ có phải đền bù gì cho tôi không vì công việc quá nặng nhọc."""

print("[1] INTENT CLASSIFICATION")
print("="*80)
intent_result = classify_intent(QUERY)
print(f"Intent: {intent_result.intent}")
print(f"Source: {intent_result.source}")

# Load resources
print("\n[2] LOADING RESOURCES")
print("="*80)

embeddings = HuggingFaceEmbeddings(
    model_name=EMBED_MODEL
)
print("Embeddings loaded")

vector_db = Chroma(
    collection_name="legal_chunks",
    embedding_function=embeddings,
    persist_directory=DB_PATH
)
retriever = vector_db.as_retriever(search_kwargs={"k": 6})
print("Vector DB loaded")

llm_extract = ChatOllama(model=LLM_MODEL, format="json", temperature=0.1)
llm_reason = ChatOllama(model=LLM_MODEL, temperature=0.1)
print("LLM loaded")

with open(ANSWER_PROMPT_PATH, encoding="utf-8") as f:
    system_prompt = f.read()
print("System prompt loaded")

# Initialize engine
engine = LegalReasoningEngine(
    retriever=retriever,
    llm_extract=llm_extract,
    llm_reason=llm_reason,
    system_prompt=system_prompt
)
print("Engine initialized")

# Analyzer
print("\n[3] ANALYZER OUTPUT")
print("="*80)
print("Input query (first 120 chars): " + QUERY[:120] + "...")

start = time.time()
analyzer_response = engine.analyzer_chain.invoke({
    "input": QUERY,
    "chat_history": []
})
analyzer_time = time.time() - start

print(f"Analyzer response time: {analyzer_time:.2f}s")
print(f"Issue: {analyzer_response.get('issue', 'N/A')}")
keywords = analyzer_response.get("keywords", [])
print(f"Keywords extracted: {keywords}")

# Retrieval
print("\n[4] RETRIEVAL TRACE")
print("="*80)

top_6_all = []
for keyword in keywords:
    print(f"  Searching: '{keyword}'")
    results = vector_db.similarity_search_with_score(keyword, k=6)
    top_6_all.extend(results)
    for i, (doc, score) in enumerate(results[:2], 1):
        dieu = doc.metadata.get("dieu_so", "?")
        page = doc.metadata.get("page", "?")
        print(f"    [{i}] Dieu {dieu} (p{page}) score={score:.4f}")

# Deduplicate top 6
seen = set()
top_6 = []
for doc, score in sorted(top_6_all, key=lambda x: -x[1]):
    key = (doc.metadata.get("dieu_so"), doc.metadata.get("page"))
    if key not in seen and len(top_6) < 6:
        seen.add(key)
        top_6.append((doc, score))

print(f"\nFinal top 6 retrieved:")
for i, (doc, score) in enumerate(top_6, 1):
    dieu = doc.metadata.get("dieu_so", "?")
    page = doc.metadata.get("page", "?")
    text_preview = doc.page_content[:80].replace("\n", " ")
    print(f"  [{i}] Dieu {dieu} (p{page}) score={score:.4f}")
    print(f"      {text_preview}...")

# Guardrails
print("\n[5] GUARDRAIL CHECKS")
print("="*80)

# Check underage mention
underage_keywords = ["tốt nghiệp cấp 2", "cấp 2", "dưới 15", "chưa thành niên"]
has_underage = any(kw in QUERY.lower() for kw in underage_keywords)
print(f"Mentions underage/child labor: {has_underage}")
if has_underage:
    print("  => Should trigger: Dieu 147-149 (child labor protection)")

# Check working hours
hours_mention = "10h sáng đến 10h đêm" in QUERY
print(f"Mentions excessive working hours (10h-22h): {hours_mention}")
if hours_mention:
    print("  => Should trigger: Dieu 95 (working hour limits)")
    print("  => Especially: Dieu 116-118 (for minors)")

# Check no contract
no_contract = "không có hợp đồng" in QUERY
print(f"Mentions no written contract: {no_contract}")
if no_contract:
    print("  => Should trigger: Dieu 24-28 (contract requirement)")

# Check underpayment
underpay = "ứng lương" in QUERY or "400k" in QUERY
print(f"Mentions wage issues: {underpay}")

# What's missing
print("\n[6] EXPECTED vs ACTUAL ARTICLES")
print("="*80)

expected = {
    "Dieu 147-149": "Bao ve tre em / nhan han (du 15 tuoi)",
    "Dieu 95": "Thoi gian lam viec toi da",
    "Dieu 116-118": "Bao ve lao dong du 18 tuoi - cam lam viec nang nhoc",
    "Dieu 24-28": "Hop dong lao dong (yeu cau viet)",
    "Dieu 94": "Tra luong (dung han, du luong)",
    "Dieu 140": "Sa thải trai phep / Cham dut HD",
}

retrieved_dieus = set()
for doc, _ in top_6:
    dieu = doc.metadata.get("dieu_so", "?")
    if dieu != "?":
        retrieved_dieus.add(dieu)

print("Expected to retrieve:")
for dieu, desc in expected.items():
    print(f"  {dieu}: {desc}")

print(f"\nActually retrieved: {sorted(retrieved_dieus)}")

missing = []
for dieu in expected.keys():
    dieu_num = dieu.replace("Dieu ", "").split("-")[0]
    if dieu_num not in retrieved_dieus:
        missing.append(dieu)

if missing:
    print(f"\nMISSING: {missing}")
else:
    print("All expected articles retrieved")

print("\n" + "="*80)
print("DEBUG TRACE COMPLETE")
print("="*80)
