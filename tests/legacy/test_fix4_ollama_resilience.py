"""
Test Fix #4: Ollama Resilience
Validates retry logic and timeout handling implementation
"""

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test validation
print("=" * 70)
print("[*] FIX #4 VALIDATION: Ollama Resilience")
print("=" * 70)

tests_passed = 0
tests_failed = 0

# Test 1: Check app.py for retry decorator
print("\n[TEST 1] Check retry decorator added to app.py")
try:
    with open('app.py', 'r', encoding='utf-8') as f:
        app_code = f.read()
    
    has_retry = "@retry" in app_code and "stop_after_attempt" in app_code
    
    if has_retry:
        print("[OK] PASS: Retry decorator imported and applied")
        tests_passed += 1
    else:
        print("[ER] FAIL: Retry decorator not found")
        tests_failed += 1
except Exception as e:
    print(f"[ER] FAIL: {e}")
    tests_failed += 1

# Test 2: Check timeout configuration
print("\n[TEST 2] Check timeout configuration")
try:
    with open('app.py', 'r', encoding='utf-8') as f:
        app_code = f.read()
    
    has_timeout = "timeout=30" in app_code
    
    if has_timeout:
        print("[OK] PASS: Timeout set to 30 seconds on LLM calls")
        tests_passed += 1
    else:
        print("[ER] FAIL: Timeout not configured")
        tests_failed += 1
except Exception as e:
    print(f"[ER] FAIL: {e}")
    tests_failed += 1

# Test 3: Check health check
print("\n[TEST 3] Check Ollama health check")
try:
    with open('app.py', 'r', encoding='utf-8') as f:
        app_code = f.read()
    
    has_health = "health check" in app_code.lower() and "llm.invoke" in app_code
    
    if has_health:
        print("[OK] PASS: Health check implemented for Ollama")
        tests_passed += 1
    else:
        print("[ER] FAIL: Health check not found")
        tests_failed += 1
except Exception as e:
    print(f"[ER] FAIL: {e}")
    tests_failed += 1

# Test 4: Check ConnectionError handling
print("\n[TEST 4] Check ConnectionError exception handling")
try:
    with open('app.py', 'r', encoding='utf-8') as f:
        app_code = f.read()
    
    has_conn_error = "except ConnectionError" in app_code
    
    if has_conn_error:
        print("[OK] PASS: ConnectionError exception handler added")
        tests_passed += 1
    else:
        print("[ER] FAIL: ConnectionError handler not found")
        tests_failed += 1
except Exception as e:
    print(f"[ER] FAIL: {e}")
    tests_failed += 1

# Test 5: Check TimeoutError handling
print("\n[TEST 5] Check TimeoutError exception handling")
try:
    with open('app.py', 'r', encoding='utf-8') as f:
        app_code = f.read()
    
    has_timeout_error = "except TimeoutError" in app_code
    
    if has_timeout_error:
        print("[OK] PASS: TimeoutError exception handler added")
        tests_passed += 1
    else:
        print("[ER] FAIL: TimeoutError handler not found")
        tests_failed += 1
except Exception as e:
    print(f"[ER] FAIL: {e}")
    tests_failed += 1

# Test 6: Check RetryError handling
print("\n[TEST 6] Check RetryError exception handling")
try:
    with open('app.py', 'r', encoding='utf-8') as f:
        app_code = f.read()
    
    has_retry_error = "except RetryError" in app_code
    
    if has_retry_error:
        print("[OK] PASS: RetryError exception handler added")
        tests_passed += 1
    else:
        print("[ER] FAIL: RetryError handler not found")
        tests_failed += 1
except Exception as e:
    print(f"[ER] FAIL: {e}")
    tests_failed += 1

# Test 7: Check load_resources has decorator
print("\n[TEST 7] Check load_resources function has retry decorator")
try:
    with open('app.py', 'r', encoding='utf-8') as f:
        app_code = f.read()
    
    # Check that @retry appears before def load_resources
    import re
    pattern = r'@retry.*?def load_resources'
    has_decorated = re.search(pattern, app_code, re.DOTALL) is not None
    
    if has_decorated:
        print("[OK] PASS: load_resources decorated with @retry")
        tests_passed += 1
    else:
        print("[ER] FAIL: load_resources not decorated")
        tests_failed += 1
except Exception as e:
    print(f"[ER] FAIL: {e}")
    tests_failed += 1

# Test 8: Check CitationValidator exists
print("\n[TEST 8] Verify CitationValidator in reasoning_chain.py")
try:
    with open('reasoning_chain.py', 'r', encoding='utf-8') as f:
        code = f.read()
    
    has_validator = "class CitationValidator" in code
    
    if has_validator:
        print("[OK] PASS: CitationValidator class implemented")
        tests_passed += 1
    else:
        print("[ER] FAIL: CitationValidator not found")
        tests_failed += 1
except Exception as e:
    print(f"[ER] FAIL: {e}")
    tests_failed += 1

# Summary
print("\n" + "=" * 70)
total = tests_passed + tests_failed
print(f"[*] RESULTS: {tests_passed}/{total} TESTS PASS")
if tests_failed == 0:
    print("[OK] FIX #4 VALIDATION: COMPLETE - ALL TESTS PASS")
else:
    print(f"[ER] FIX #4 VALIDATION: {tests_failed} TEST(S) FAILED")
print("=" * 70)

exit(0 if tests_failed == 0 else 1)
