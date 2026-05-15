"""
Quick validation of Fix #2: Analyzer prompt improvements
Checks that the code has been updated without needing to run Ollama
"""

import re
import sys

def validate_fix2():
    """Validate Fix #2 implementation by checking code"""
    print("=" * 70)
    print("[*] FIX #2 VALIDATION: Analyzer Keyword Improvements")
    print("=" * 70)
    
    # Read the modified file
    with open('reasoning_chain.py', 'r', encoding='utf-8') as f:
        code = f.read()
    
    checks = {}
    
    # Check 1: Few-shot examples present (check for Vietnamese text directly)
    checks["Few-shot examples"] = "MẤU VÍ DỤ ĐÚNG" in code
    
    # Check 2: Forbidden list present
    checks["Forbidden list"] = "KHÔNG DÙNG từ chung chung" in code
    
    # Check 3: Domain guidance present
    checks["Domain guidance"] = "GỢI Ý THEO CHỦ ĐỀ" in code
    
    # Check 4: Specific keywords emphasis
    checks["Specific keywords"] = "CỤ THỀ" in code
    
    # Check 5: Examples present
    checks["Examples section"] = "INPUT:" in code and "OUTPUT:" in code
    
    # Check 6: Domain guidance section  
    checks["Domain sections"] = "SA THẢI" in code and "LƯƠNG" in code and "MANG THAI" in code
    
    # Check 7: JSON format spec
    checks["JSON format"] = '"issue"' in code and '"keywords"' in code and '"law_type"' in code
    
    for name, result in checks.items():
        status = "[OK]" if result else "[ER]"
        print(f"{status} {name}: {'PASS' if result else 'FAIL'}")
    
    passed = sum(checks.values())
    total = len(checks)
    
    print("=" * 70)
    if passed == total:
        print(f"[OK] FIX #2 VALIDATION: {passed}/{total} PASS - IMPLEMENTATION COMPLETE")
        return True
    else:
        print(f"[ER] FIX #2 VALIDATION: {passed}/{total} PASS - INCOMPLETE")
        return False

if __name__ == "__main__":
    success = validate_fix2()
    exit(0 if success else 1)
