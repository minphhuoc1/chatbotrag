from __future__ import annotations

import re
from collections import Counter
from typing import Dict


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def detect_runaway_generation(answer: str) -> Dict:
    """
    Detect repetitive runaway generations that often appear as token loops.
    """
    norm = _normalize_text(answer)
    if not norm:
        return {"is_runaway": False, "reason": "empty", "max_ngram_repeat": 0}

    words = re.findall(r"[\wÀ-ỹ]+", norm)
    if len(words) < 40:
        return {"is_runaway": False, "reason": "too_short", "max_ngram_repeat": 0}

    max_repeat = 0
    max_phrase = ""
    max_ngram_size = 0
    for n in (10, 8, 6):
        grams = [tuple(words[i:i + n]) for i in range(0, max(0, len(words) - n + 1))]
        if not grams:
            continue
        phrase, repeat = Counter(grams).most_common(1)[0]
        if repeat > max_repeat:
            max_repeat = repeat
            max_phrase = " ".join(phrase)
            max_ngram_size = n

    repetitive_clause = re.search(r"(.{45,180}?)(?:\s+\1){2,}", norm)
    clause_hit = repetitive_clause is not None

    # Legal texts naturally repeat short terms such as "hợp đồng lao động".
    # Treat only long repeated spans or exact repeated clauses as runaway.
    is_runaway = (max_ngram_size >= 6 and max_repeat >= 5) or clause_hit
    reason = "repetitive_ngram_loop" if is_runaway else "ok"
    return {
        "is_runaway": is_runaway,
        "reason": reason,
        "max_ngram_repeat": int(max_repeat),
        "repetitive_phrase": max_phrase[:220],
    }
