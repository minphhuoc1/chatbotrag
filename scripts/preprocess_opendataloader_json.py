"""
Sinh JSON preprocess bằng OpenDataLoader (Fast mode mặc định).

Yêu cầu:
    pip install -U opendataloader-pdf
"""

import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
VENDOR_DIR = ROOT_DIR / ".vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    import jdk4py
except ImportError:
    jdk4py = None

if jdk4py is not None:
    os.environ.setdefault("JAVA_HOME", str(jdk4py.JAVA_HOME))
    java_bin = str(Path(jdk4py.JAVA_HOME) / "bin")
    current_path = os.environ.get("PATH", "")
    if java_bin not in current_path:
        os.environ["PATH"] = f"{java_bin};{current_path}"

try:
    import opendataloader_pdf
except ImportError as exc:
    raise SystemExit(
        "Thiếu package 'opendataloader-pdf'. "
        "Cài bằng: pip install -U opendataloader-pdf"
    ) from exc


DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = DATA_DIR / "preprocessed"

# Nếu đủ file đích thì dùng list. Nếu thiếu, fallback parse cả thư mục data/.
TARGET_FILES = [
    DATA_DIR / "luatlaodong_new.pdf",
    DATA_DIR / "nghidinh_145.pdf",
]


def resolve_input_path():
    existing = [str(p) for p in TARGET_FILES if p.exists()]
    if len(existing) == len(TARGET_FILES):
        return existing
    return str(DATA_DIR)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    input_path = resolve_input_path()

    print("OpenDataLoader preprocess (Fast mode mặc định)")
    print(f"  input_path: {input_path}")
    print(f"  output_dir: {OUTPUT_DIR}")
    print("  format: json")

    # ĐÚNG: Truyền thẳng thư mục hoặc mảng danh sách file vào một lần gọi duy nhất.
    opendataloader_pdf.convert(
        input_path=input_path,
        output_dir=str(OUTPUT_DIR),
        format="json",
    )

    print("✅ Hoàn tất preprocess JSON.")


if __name__ == "__main__":
    main()
