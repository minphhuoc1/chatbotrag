#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Deploy this repo to a Hugging Face Docker Space.

Usage:
    python scripts/deploy_hf_space.py --repo-id <username-or-org>/<space-name>

Authentication:
    Set HF_TOKEN or HUGGINGFACEHUB_API_TOKEN in the environment, or run:
        hf auth login
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from huggingface_hub import HfApi


ROOT = Path(__file__).resolve().parents[1]

IGNORE_PATTERNS = [
    ".git/*",
    ".codex/*",
    ".env",
    ".env.*",
    "!/.env.example",
    "frontend/.env.local",
    "frontend/.env.*.local",
    ".venv/*",
    "venv/*",
    ".vendor/*",
    ".tools/*",
    ".hf_cache*/*",
    ".pip-cache/*",
    "__pycache__/*",
    "**/__pycache__/*",
    "*.pyc",
    ".pytest_cache/*",
    "pytest-cache-files-*/*",
    "frontend/node_modules/*",
    "frontend/.next/*",
    "frontend/tsconfig.tsbuildinfo",
    "node_modules/*",
    ".next/*",
    "reports/*",
    "logs/*",
    "artifacts/*",
    "backup/*",
    "tmp/*",
    "tmp_*/*",
    "OllamaSetup.exe",
    "project_logic_map.md",
    "tmp_readme.md",
    "pdf_analysis_report.txt",
    "0.34.0",
    "vector_db_*/*",
    "vector_db_qa*/*",
    "vector_db_corrupt_*/*",
]


def _get_token() -> str | None:
    return (
        os.getenv("HF_TOKEN")
        or os.getenv("HUGGINGFACEHUB_API_TOKEN")
        or os.getenv("HUGGING_FACE_HUB_TOKEN")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy LexBot to Hugging Face Spaces.")
    parser.add_argument(
        "--repo-id",
        required=True,
        help="Hugging Face Space repo id, e.g. username/lexbot-vietnam-labor-law",
    )
    parser.add_argument("--private", action="store_true", help="Create/update a private Space.")
    parser.add_argument(
        "--commit-message",
        default="Deploy LexBot Docker Space",
        help="Commit message for the Space upload.",
    )
    args = parser.parse_args()

    token = _get_token()
    api = HfApi(token=token)
    if token is None:
        # This still works when the user has run `hf auth login`.
        print("HF_TOKEN is not set. Falling back to cached Hugging Face CLI login.")

    api.create_repo(
        repo_id=args.repo_id,
        repo_type="space",
        space_sdk="docker",
        private=args.private,
        exist_ok=True,
    )

    api.upload_folder(
        repo_id=args.repo_id,
        repo_type="space",
        folder_path=str(ROOT),
        path_in_repo=".",
        ignore_patterns=IGNORE_PATTERNS,
        commit_message=args.commit_message,
    )
    print(f"Deployed to https://huggingface.co/spaces/{args.repo_id}")
    print(f"Live app URL: https://{args.repo_id.replace('/', '-')}.hf.space")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
