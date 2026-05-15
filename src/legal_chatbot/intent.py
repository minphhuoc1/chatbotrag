# -*- coding: utf-8 -*-
"""
intent.py — Phân loại ý định người dùng trước khi route vào pipeline.

3 loại intent:
  - GREETING   : chào hỏi, cảm ơn, xã giao đơn giản
  - OFF_TOPIC  : câu hỏi không liên quan đến luật/pháp lý
  - LEGAL      : câu hỏi pháp lý → cần tra cứu RAG

Cách hoạt động (hybrid 2 tầng):
  Tầng 1 — Rule-based (0ms, không tốn VRAM):
    Bắt rõ các pattern greeting và off-topic bằng keyword/regex.
    Nếu confident → trả kết quả ngay.
  Tầng 2 — LLM prompt ngắn (chỉ gọi khi tầng 1 uncertain):
    Dùng cùng model đang chạy, prompt 1 dòng → trả về 1 trong 3 nhãn.

Lý do không dùng model riêng cho intent:
  GTX 1650 chỉ có 4GB VRAM. Load 2 model cùng lúc → crash.
"""

import re
from dataclasses import dataclass
from enum import Enum


class Intent(str, Enum):
    GREETING  = "GREETING"
    OFF_TOPIC = "OFF_TOPIC"
    LEGAL     = "LEGAL"


@dataclass
class IntentResult:
    intent  : Intent
    response: str   # Câu trả lời mặc định cho GREETING/OFF_TOPIC, rỗng cho LEGAL
    source  : str   # "rule" hoặc "llm" — để debug


# ── Câu trả lời mặc định (không cần gọi LLM) ─────────────────────────────────

GREETING_RESPONSES = [
    "Xin chào! Tôi là trợ lý tư vấn pháp luật lao động. Bạn có câu hỏi gì về quyền lợi lao động, hợp đồng, lương thưởng, hoặc các quy định trong Bộ luật Lao động không? 😊",
    "Chào bạn! Rất vui được hỗ trợ bạn về các vấn đề pháp lý lao động hôm nay. Bạn cần tư vấn về vấn đề gì?",
    "Hi! Tôi ở đây để giúp bạn tìm hiểu về Bộ luật Lao động Việt Nam. Bạn đang gặp vấn đề gì liên quan đến quyền lao động?",
]

OFF_TOPIC_RESPONSES = [
    "Câu hỏi thú vị đấy! Tuy nhiên, mình chỉ có thể hỗ trợ các vấn đề về pháp luật lao động Việt Nam như quyền lợi người lao động, hợp đồng lao động, lương thưởng, kỷ luật lao động... Bạn có câu hỏi nào về những chủ đề này không?",
    "Mình hiểu bạn đang hỏi về điều đó, nhưng phạm vi hỗ trợ của mình là pháp luật lao động Việt Nam. Nếu bạn có thắc mắc về quyền lợi lao động, hợp đồng, sa thải, nghỉ phép... mình sẽ trả lời ngay!",
    "Điều đó nằm ngoài phạm vi chuyên môn của mình rồi 😅 Mình chỉ hỗ trợ tư vấn về Bộ luật Lao động Việt Nam. Bạn có câu hỏi nào về luật lao động không?",
]

# ── Tầng 1: Rule-based patterns ───────────────────────────────────────────────

# Pattern GREETING — phải khớp TOÀN BỘ câu, không phải một phần
# (tránh "xin chào về điều 35" bị classify thành GREETING)
GREETING_PATTERNS = [
    r"^(xin\s+chào|chào|hello|hi|hey|hé|ê|yo)\b",
    r"^(bạn\s+khỏe\s+không|khỏe\s+không|how\s+are\s+you)",
    r"^(cảm\s+ơn|cám\s+ơn|thanks|thank\s+you|tks)\b",
    r"^(ok|okay|ổn|được|tốt|hiểu\s+rồi|rõ\s+rồi)\s*[!.]*$",
    r"^(tạm\s+biệt|bye|goodbye|hẹn\s+gặp|gặp\s+lại)\b",
    r"^(bạn\s+là\s+ai|mày\s+là\s+ai|you\s+are\s+who|giới\s+thiệu\s+bản\s+thân)",
    r"^(bạn\s+làm\s+được\s+gì|bạn\s+giỏi\s+gì|bạn\s+hỗ\s+trợ\s+gì)",
]

# Keyword nặng OFF_TOPIC — nếu xuất hiện VÀ không có keyword pháp lý → OFF_TOPIC
OFF_TOPIC_KEYWORDS = [
    # Ẩm thực
    "ăn gì", "uống gì", "nấu ăn", "món ăn", "nhà hàng", "quán ăn", "cơm", "phở",
    # Thời tiết
    "thời tiết", "trời", "mưa", "nắng", "nhiệt độ",
    # Giải trí
    "xem phim", "nghe nhạc", "bài hát", "ca sĩ", "diễn viên", "bóng đá", "thể thao",
    "real madrid", "barcelona", "man utd", "liverpool", "arsenal", "champions league",
    # Công nghệ không liên quan
    "blockchain", "bitcoin", "crypto", "nft", "ai là gì", "chatgpt",
    # Sức khỏe (không phải tai nạn lao động)
    "thuốc", "triệu chứng",
    # Địa lý, du lịch
    "du lịch", "khách sạn", "vé máy bay", "địa điểm",
    # Tình cảm
    "người yêu", "bạn gái", "bạn trai", "cưới",
    # Học thuật không phải luật
    "toán học", "vật lý", "hóa học", "lập trình",
]

# Keyword pháp lý — nếu có những từ này, KHÔNG classify OFF_TOPIC dù có OT keyword
LEGAL_KEYWORDS = [
    "luật", "điều", "khoản", "điểm", "bộ luật", "pháp luật", "quy định",
    "hợp đồng", "lao động", "người lao động", "người sử dụng lao động",
    "sa thải", "thôi việc", "nghỉ phép", "lương", "thưởng", "trợ cấp", "tiền công",
    "bảo hiểm", "tai nạn", "kỷ luật", "tranh chấp", "đình công",
    "thử việc", "mang thai", "thai sản", "nghỉ hưu",
    "vi phạm", "xử phạt", "bồi thường", "khiếu nại",
    "chấm dứt hợp đồng", "đơn phương", "thời gian làm việc",
    "thời giờ làm việc", "làm thêm giờ", "nghỉ lễ", "ngày lễ", "tiền lương",
]


def _keyword_in_text(text_lower: str, keyword: str) -> bool:
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return False
    if " " in keyword:
        return keyword in text_lower
    return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text_lower) is not None


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    text_lower = text.lower()
    return [kw for kw in keywords if _keyword_in_text(text_lower, kw)]


def _has_legal_keyword(text: str) -> bool:
    return bool(_matched_keywords(text, LEGAL_KEYWORDS))


def _has_offtopic_keyword(text: str) -> bool:
    return bool(_matched_keywords(text, OFF_TOPIC_KEYWORDS))


def _looks_like_legal_followup_prompt(last_bot_message: str) -> bool:
    """
    Chỉ coi là legal follow-up khi câu trả lời gần nhất của bot thực sự là
    câu hỏi làm rõ thêm dữ kiện.
    Tránh match nhầm với câu trả lời nội dung dài có chứa cụm như "thông báo trước".
    """
    text = (last_bot_message or "").strip().lower()
    if not text:
        return False

    # Không treat các câu trả lời dài là follow-up question.
    if len(text) > 320:
        return False

    # Heuristic chính: phải là câu hỏi làm rõ.
    has_question_mark = "?" in text
    followup_patterns = [
        "bạn có thể cho biết",
        "bạn vui lòng nêu rõ",
        "bạn có thể nêu rõ",
        "cho biết thêm",
        "để tôi trả lời chính xác",
        "để tôi kiểm tra chính xác",
        "bạn đang hỏi trường hợp nào",
        "bạn đang hỏi theo trường hợp nào",
        "bạn đang hỏi điều",
    ]
    has_followup_pattern = any(pat in text for pat in followup_patterns)
    ends_like_question = text.rstrip().endswith("?")
    return has_question_mark and has_followup_pattern and ends_like_question


def _classify_rule_based(text: str) -> IntentResult | None:
    """
    Tầng 1: Rule-based classifier.
    Trả về IntentResult nếu confident, None nếu uncertain.
    """
    import random
    text_stripped = text.strip()
    text_lower    = text_stripped.lower()

    # — 1. Nếu có từ khóa pháp lý rõ → ƯU TIÊN là LEGAL ngay lập tức
    # (Tránh việc "xin chào, tôi muốn hỏi về điều 35" bị nhầm thành GREETING)
    if _has_legal_keyword(text_lower):
        return IntentResult(intent=Intent.LEGAL, response="", source="rule")

    # — 2. GREETING: câu ngắn (<= 10 từ) khớp greeting pattern
    if len(text_stripped.split()) <= 10:
        for pattern in GREETING_PATTERNS:
            if re.search(pattern, text_lower):
                return IntentResult(
                    intent=Intent.GREETING,
                    response=random.choice(GREETING_RESPONSES),
                    source="rule",
                )

    # — 3. OFF_TOPIC: có keyword off-topic VÀ không có keyword pháp lý
    ot_found = _matched_keywords(text_lower, OFF_TOPIC_KEYWORDS)
    if ot_found:
        return IntentResult(
            intent=Intent.OFF_TOPIC,
            response=random.choice(OFF_TOPIC_RESPONSES),
            source="rule",
        )

    # — Không đủ confident → để Tầng 2 xử lý
    return None


# ── Tầng 2: LLM-based (chỉ gọi khi rule không chắc) ─────────────────────────

INTENT_PROMPT = """Phân loại câu hỏi sau vào 1 trong 3 nhóm:
- GREETING: chào hỏi, cảm ơn, câu xã giao đơn giản, hỏi về bản thân bot
- LEGAL: câu hỏi về luật pháp, quyền lợi, hợp đồng, lao động, vi phạm pháp luật
- OFF_TOPIC: câu hỏi không liên quan luật (ẩm thực, giải trí, công nghệ, v.v.)

Chỉ trả lời đúng 1 từ: GREETING hoặc LEGAL hoặc OFF_TOPIC

Câu hỏi: {question}
Nhóm:"""


def _classify_llm(text: str, llm) -> IntentResult:
    """
    Tầng 2: Gọi LLM với prompt cực ngắn.
    Chỉ gọi khi rule-based không confident.
    """
    import random
    prompt = INTENT_PROMPT.format(question=text)
    try:
        response = llm.invoke(prompt)
        # Lấy content từ AIMessage hoặc string
        raw = response.content if hasattr(response, "content") else str(response)
        raw = raw.strip().upper()

        if "GREETING" in raw:
            return IntentResult(
                intent=Intent.GREETING,
                response=random.choice(GREETING_RESPONSES),
                source="llm",
            )
        elif "OFF_TOPIC" in raw or "OFF-TOPIC" in raw:
            return IntentResult(
                intent=Intent.OFF_TOPIC,
                response=random.choice(OFF_TOPIC_RESPONSES),
                source="llm",
            )
        else:
            # Mọi trường hợp không rõ → an toàn là LEGAL
            return IntentResult(intent=Intent.LEGAL, response="", source="llm")
    except Exception:
        # Nếu LLM fail:
        # - Nếu thấy rõ off-topic và không có keyword pháp lý => OFF_TOPIC
        # - Ngược lại giữ LEGAL để tránh bỏ sót câu pháp lý thật.
        import random
        text_lower = text.lower()
        has_offtopic = bool(_matched_keywords(text_lower, OFF_TOPIC_KEYWORDS))
        if has_offtopic and not _has_legal_keyword(text_lower):
            return IntentResult(
                intent=Intent.OFF_TOPIC,
                response=random.choice(OFF_TOPIC_RESPONSES),
                source="llm_fallback_rule_offtopic",
            )
        return IntentResult(intent=Intent.LEGAL, response="", source="llm_fallback")


# ── Public API ────────────────────────────────────────────────────────────────

def classify_intent(text: str, llm=None, chat_history: list = None) -> IntentResult:
    """
    Phân loại intent của câu hỏi người dùng.

    Args:
        text:         Câu hỏi người dùng
        llm:          Ollama LLM instance (chỉ cần nếu muốn dùng Tầng 2).
        chat_history: Lịch sử hội thoại LangChain Messages.
                      Nếu bot vừa hỏi thêm thông tin pháp lý, follow-up mặc định là LEGAL.

    Returns:
        IntentResult với intent, response mặc định (nếu có), và source.
    """
    text = text.strip()
    if not text:
        import random
        return IntentResult(
            intent=Intent.GREETING,
            response=random.choice(GREETING_RESPONSES),
            source="rule",
        )

    text_lower = text.lower()
    if _has_offtopic_keyword(text_lower) and not _has_legal_keyword(text_lower):
        import random
        return IntentResult(
            intent=Intent.OFF_TOPIC,
            response=random.choice(OFF_TOPIC_RESPONSES),
            source="rule_offtopic_guard",
        )

    # ── Kiểm tra ngữ cảnh hội thoại TRƯỚC khi phân loại ────────────────────
    # Vấn đề: "Mình làm IT và công ty có thỏa thuận rồi" không có keyword pháp lý
    # nhưng là câu trả lời follow-up cho câu hỏi của bot về tình huống pháp lý.
    # Fix: Nếu AIMessage gần nhất cho thấy bot đang hỏi thêm thông tin pháp lý,
    # treat follow-up là LEGAL thay vì để LLM phân loại sai.
    if chat_history:
        from langchain_core.messages import AIMessage as _AIMsg
        last_ai_msgs = [m for m in chat_history if isinstance(m, _AIMsg)]
        if last_ai_msgs:
            last_bot = str(last_ai_msgs[-1].content or "").lower()
            in_legal_followup = _looks_like_legal_followup_prompt(last_bot)
            if in_legal_followup:
                # Chỉ bỏ qua nếu câu mới là GREETING rõ ràng (ngắn + pattern rõ)
                is_clear_greeting = (
                    len(text.split()) <= 5 and
                    any(re.search(pat, text_lower) for pat in GREETING_PATTERNS)
                )
                if not is_clear_greeting:
                    return IntentResult(
                        intent=Intent.LEGAL,
                        response="",
                        source="context_carry",  # giữ ngữ cảnh hội thoại pháp lý
                    )

    # Tầng 1: rule-based (luôn chạy trước)
    result = _classify_rule_based(text)
    if result is not None:
        return result

    # Tầng 2: LLM (chỉ khi rule uncertain)
    if llm is not None:
        return _classify_llm(text, llm)

    # Không có LLM → fallback an toàn là LEGAL
    return IntentResult(intent=Intent.LEGAL, response="", source="rule_uncertain_fallback")
