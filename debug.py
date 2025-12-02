import sys
import os

print("--- PYTHON EXECUTABLE ---")
print(sys.executable)
print("\n--- INSTALLED PACKAGES LOCATION ---")
for p in sys.path:
    print(p)

try:
    import langchain
    print(f"\n✅ LangChain version: {langchain.__version__}")
    from langchain import chains
    print("✅ Import langchain.chains thành công!")
except ImportError as e:
    print(f"\n❌ Lỗi Import: {e}")