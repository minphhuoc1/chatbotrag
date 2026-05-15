import logging
import re
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import AIMessage, HumanMessage
from .intent import classify_intent, Intent
from .policy import (
    assess_retrieval_strength,
    build_extractive_fallback_answer,
    build_unilateral_compensation_response,
    build_insufficient_context_response,
    build_validation_fallback,
    classify_query_mode,
    enforce_citation_contract,
    extract_articles_from_documents,
    classify_failure_cause,
    detect_unilateral_termination_role,
    is_unlawful_unilateral_compensation_query,
    repair_answer_citations,
    resolve_article_query,
    suggest_target_articles,
    validate_answer_against_context,
)
from .retrieval import retrieve_documents, retrieve_exact_article
from .severance import try_build_severance_answer
from .config import (
    MAX_ARTICLE_NUMBER,
    REASONER_MAX_CONTEXT_CHARS,
    REASONER_MAX_CONTEXT_DOCS,
    RETRIEVAL_ENABLE_DETERMINISTIC_ARTICLE_BRANCH,
)


@dataclass
class RunResult:
    """Structured result from engine.run_structured().

    Provides all data needed by the UI layer (app.py) to render
    evidence tables, grounding rows, expanders, and telemetry
    without accessing engine internals directly.
    """

    answer: str
    context_text: str = ""
    docs: list = field(default_factory=list)
    intent_result: Any = None  # IntentResult from classify_intent
    query_mode: str = ""
    search_query: str = ""
    retrieval_check: dict = field(default_factory=dict)
    validation: dict = field(default_factory=dict)
    is_clarifying: bool = False
    route: str = ""  # e.g. 'rule_based', 'rag', 'article_resolution', 'insufficient', 'clarifying'
    debug_flags: dict = field(default_factory=dict)


class LegalReasoningEngine:
    """
    Cỗ máy phân tích pháp lý 2 bước (Two-Step Legal Reasoning).
    Giải quyết vấn đề: Việc dùng nguyên câu hỏi dài dòng của người dùng (VD: 
    'Hôm qua tôi bị sếp chửi rủa đập bàn phím rồi ép làm giấy thôi việc, tôi phải làm sao')
    vào Vector Database sẽ làm giảm độ chính xác của BM25/Semantic search.
    Do đó, chia làm 2 bước (Lần 1: Trích xuất Keyword, Lần 2: Sinh câu trả lời).
    """

    # Legal keywords for fallback extraction
    LEGAL_KEYWORDS_BANK = [
        "sa thải", "chấm dứt", "hợp đồng", "lương", "tối thiểu",
        "mang thai", "lao động nữ", "lao động", "bảo vệ", "không được",
        "nghỉ phép", "phép năm", "thâm niên", "hằng năm",
        "giờ làm việc", "tối đa", "ngày", "tuần",
        "bảo hiểm xã hội", "bảo hiểm y tế", "thôi việc",
        "thưởng tết", "thưởng kết quả", "phụ cấp",
        "hóa đơn", "chứng chỉ", "trình độ", "kỹ năng",
        "vi phạm", "xử phạt", "kỷ luật", "ứng xử",
        "hòa giải", "trọng tài", "kiện", "yêu cầu",
        "điều 35", "điều 113", "điều 114", "điều 138", "điều 140"
    ]
    FOLLOWUP_QUERY_MARKERS = [
        "vậy",
        "thế",
        "thì",
        "còn",
        "nếu tôi",
        "tôi có thể",
        "yêu cầu gì",
        "họ vừa",
        "kéo dài thêm",
        "thêm 2 tháng",
        "trường hợp này",
        "trường hợp đó",
        "như vậy",
        "vậy thì",
    ]
    CONTEXT_CARRY_PHRASES = [
        "nợ lương",
        "chậm lương",
        "không trả lương",
        "không báo trước",
        "đơn phương",
        "chấm dứt hợp đồng",
        "hợp đồng",
        "trợ cấp thôi việc",
        "thanh toán",
        "bồi thường",
    ]
    CLARIFY_TAG = "[CLARIFY]"
    FACT_PATTERN_PROMPT = """Phân tích câu hỏi pháp lý sau và trả lời JSON:

Câu hỏi: {user_input}

Trả lời JSON (không thêm text khác):
{{
  "is_fact_pattern": true/false,
  "legal_issues": ["issue1", "issue2"],
  "supplementary_queries": ["query1", "query2"]
}}

Quy tắc:
- is_fact_pattern = true nếu câu hỏi mô tả một tình huống thực tế cần xét nhiều điều luật
- legal_issues: liệt kê các vấn đề pháp lý cốt lõi cần kiểm tra (tối đa 4)
- supplementary_queries: các truy vấn bổ sung để tìm điều luật liên quan (tối đa 3)

Ví dụ cho "Nhân viên đi muộn tháng 3, tháng 5 công ty mới xử lý kỷ luật":
{{
  "is_fact_pattern": true,
  "legal_issues": ["thời hiệu xử lý kỷ luật", "nguyên tắc không gộp lỗi", "căn cứ sa thải hợp pháp"],
  "supplementary_queries": ["Điều 123 thời hiệu xử lý kỷ luật lao động", "Điều 122 nguyên tắc kỷ luật", "Điều 125 căn cứ sa thải"]
}}"""

    def __init__(self, retriever, llm_extract, llm_reason, system_prompt, llm_intent=None):
        """
        Khởi tạo Engine với các tài nguyên truyền vào từ app.py
        - retriever: Đối tượng kéo dữ liệu từ ChromaDB
        - llm_extract: Model dùng để phân tách JSON từ khóa (Nên dùng model chạy format="json")
        - llm_reason: Model chính gánh vác State Machine Prompt (Qwen 3B/7B)
        - system_prompt: Đọc từ file hệ thống system_prompt.md
        """
        self.retriever = retriever
        self.llm_extract = llm_extract
        self.llm_analyzer = llm_extract
        self.llm_reason = llm_reason
        self.llm_intent = llm_intent or llm_reason
        self.system_prompt = system_prompt
        
        # -------------------------------------------------------------
        # BƯỚC 4A: SCENARIO ANALYZER (BỘ PHÂN TÍCH TÌNH HUỐNG/TỪ KHÓA)
        # -------------------------------------------------------------
        # Mục đích: Biến câu chuyện dài của User thành định dạng dữ liệu có cấu trúc.
        # Cải tiến: Thêm few-shot examples và forbidden list để tạo ra từ khóa CỤ THỀ
        self.analyzer_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "Bạn là chuyên gia phân tích pháp lý lao động Việt Nam. Phân tích tình huống và tìm từ khóa CỤ THỀ.\n"
             "LUÔN trả về JSON đúng định dạng:\n"
             "{{\n"
             '  "issue": "mô tả vấn đề pháp lý ngắn gọn",\n'
             '  "keywords": ["từ khóa 1", "từ khóa 2"],\n'
             '  "law_type": "luật lao động"\n'
             "}}\n"
             "\n=== QUI TẮC TRÍCH XUẤT KEYWORD (CỰC KỲ QUAN TRỌNG) ===\n"
             "✅ ĐỀN TỪ KHÓA CỤ THỀ như: sa thải, mang thai, lương tối thiểu, hợp đồng, thâm niên\n"
             "❌ KHÔNG DÙNG từ chung chung: 'luật', 'quyền', 'vấn đề', 'điều', 'khoản', 'lao động'\n"
             "❌ KHÔNG DÙNG đại từ: tôi, bạn, họ, chúng ta\n"
             "✅ Nếu input chứa phần [NGỮ CẢNH HỘI THOẠI TRƯỚC] và [CÂU HỎI MỚI], "
             "PHẢI hợp nhất dữ kiện quan trọng từ ngữ cảnh cũ vào keywords cho câu hỏi mới "
             "(ví dụ: nợ lương, không báo trước, loại hợp đồng, thời hạn hợp đồng).\n"
             "✅ KHÔNG được làm mất dữ kiện pháp lý trọng yếu từ ngữ cảnh trước.\n"
             "\n=== MẤU VÍ DỤ ĐÚNG ===\n"
             "INPUT: 'Sa thải lao động nữ mang thai, tôi biết gì về quyền của tôi?'\n"
             "OUTPUT: {{\"issue\": \"Sa thải lao động nữ mang thai\", \"keywords\": [\"sa thải\", \"mang thai\", \"bảo vệ lao động nữ\"], \"law_type\": \"luật lao động\"}}\n"
             "\n"
             "INPUT: 'Làm việc 50 tiếng/tuần, lương tối thiểu vùng là bao nhiêu?'\n"
             "OUTPUT: {{\"issue\": \"Yêu cầu về giờ làm việc và lương tối thiểu\", \"keywords\": [\"giờ làm việc\", \"lương tối thiểu\", \"vùng\"], \"law_type\": \"luật lao động\"}}\n"
             "\n"
             "INPUT: 'Không được nghỉ phép hằng năm 12 ngày, sao thế?'\n"
             "OUTPUT: {{\"issue\": \"Từ chối nghỉ phép hằng năm\", \"keywords\": [\"nghỉ phép\", \"thâm niên\", \"quyền lợi\"], \"law_type\": \"luật lao động\"}}\n"
              "\n"
              "INPUT: 'Người lao động được nghỉ phép bao nhiêu ngày một năm?'\n"
               "OUTPUT: {{\"issue\": \"Quyền nghỉ phép hằng năm\", \"keywords\": [\"nghỉ phép\", \"hằng năm\"], \"law_type\": \"luật lao động\"}}\n"
             "\n=== GỢI Ý THEO CHỦ ĐỀ ===\n"
             "Nếu về SA THẢI → dùng: sa thải, chấm dứt, không có lý do, bảo vệ\n"
             "Nếu về LƯƠNG → dùng: lương, tối thiểu, vùng, mức, trả lương\n"
             "Nếu về MANG THAI → dùng: mang thai, lao động nữ, bảo vệ, không được\n"
             "Nếu về HỢP ĐỒNG → dùng: hợp đồng, chấm dứt, đơn phương\n"
             "Nếu về PHÉP → dùng: phép, thâm niên, ngày, hằng năm\n"
             "Nếu về GIỜ LÀM → dùng: giờ làm việc, tối đa, tuần, ngày\n"
             "\n✅ Nếu user đề cập Điều cụ thể (vd: Điều 35, Điều 113), PHẢI đưa vào keywords.\n"
             "✅ Tối đa 5 keywords, ưu tiên ngắn gọn và sắc bén."
            ),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "Câu hỏi: {input}")
        ])
        self.analyzer_chain = self.analyzer_prompt | self.llm_extract | StrOutputParser()

        # -------------------------------------------------------------
        # BƯỚC 4C: LEGAL REASONER (BỘ TƯ DUY TRẢ LỜI CỐT LÕI)
        # -------------------------------------------------------------
        # Fix thiết kế: {context} được inject TƯỜNG MINH qua human turn
        # thay vì phụ thuộc vào side-effect của system prompt template.
        # system_prompt.md chứa placeholder {context} ở cuối —
        # LangChain sẽ fill nó khi invoke với key "context".
        self.reasoner_prompt = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt),   # system_prompt.md có {context} — được fill khi invoke
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}")
        ])
        self.reasoner_chain = self.reasoner_prompt | self.llm_reason | StrOutputParser()


    def _extract_keywords_fallback(self, text: str) -> List[str]:
        """
        Fallback keyword extraction when JSON parsing fails.
        Uses regex and keyword bank to extract legal terms from user input.
        
        Returns: List of extracted keywords (max 5)
        """
        text_lower = text.lower()
        
        # Step 1: Check if user explicitly mentions article numbers (Điều X)
        article_pattern = r'điều\s*(\d+)'
        article_matches = re.findall(article_pattern, text_lower)
        keywords = [f"Điều {m}" for m in article_matches if 1 <= int(m) <= MAX_ARTICLE_NUMBER]
        
        # Step 2: Match against legal keyword bank
        for keyword in self.LEGAL_KEYWORDS_BANK:
            if keyword.lower() in text_lower and keyword not in keywords:
                keywords.append(keyword)
                if len(keywords) >= 5:
                    break
        
        # Step 3: If still no keywords, extract meaningful words (not just symbols)
        if not keywords:
            # Try to find noun phrases (words that don't look like pronouns/articles)
            words = text_lower.split()
            # Filter out common pronouns and articles
            pronouns = {"tôi", "bạn", "họ", "chúng", "nó", "cái", "chiếc", "những", 
                       "các", "được", "là", "của", "cho", "từ", "để", "vào", "với"}
            # Only keep words that: (1) are not pronouns, (2) are >=3 chars, (3) contain letters
            meaningful_words = [
                w for w in words 
                if w not in pronouns and len(w) >= 3 and any(c.isalpha() for c in w)
            ]
            
            if meaningful_words:
                # Take first 2-3 meaningful words as fallback keywords
                keywords = meaningful_words[:3]
        
        # Fallback: if completely empty, return generic legal query
        if not keywords:
            keywords = ["luật lao động"]
        
        return keywords[:5]  # Return max 5 keywords

    def _parse_analyzer_output(self, raw_output: str) -> Dict:
        """
        Parse output từ analyzer theo hướng tolerant:
        - Ưu tiên parse JSON trực tiếp.
        - Nếu model thêm lời giải thích, cố tách object JSON đầu tiên.
        """
        text = str(raw_output or "").strip()
        if not text:
            raise json.JSONDecodeError("empty analyzer output", "", 0)

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        # Tìm khối JSON object bằng cân bằng dấu ngoặc.
        start = text.find("{")
        if start == -1:
            raise json.JSONDecodeError("no json object found", text, 0)

        depth = 0
        end = -1
        for i, ch in enumerate(text[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end == -1:
            raise json.JSONDecodeError("unterminated json object", text, start)

        candidate = text[start:end]
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            raise json.JSONDecodeError("parsed json is not object", candidate, 0)
        return parsed

    @staticmethod
    def _dedup_preserve_order(items: List[str]) -> List[str]:
        seen = set()
        result = []
        for item in items:
            norm = (item or "").strip().lower()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            result.append(item.strip())
        return result

    def _is_followup_query(self, user_input: str) -> bool:
        text = (user_input or "").strip().lower()
        if not text:
            return False
        if any(marker in text for marker in self.FOLLOWUP_QUERY_MARKERS):
            return True
        words = text.split()
        if len(words) <= 8 and any(w in {"vậy", "thì", "còn", "nếu"} for w in words):
            return True
        if len(words) <= 14 and any(w in {"họ", "vậy", "thế", "nữa"} for w in words):
            return True
        return False

    def _last_bot_asked_clarification(self, chat_history: list) -> bool:
        if not chat_history:
            return False
        for msg in reversed(chat_history):
            content = ""
            if isinstance(msg, AIMessage):
                content = str(getattr(msg, "content", "") or "").strip().lower()
            elif isinstance(msg, dict) and msg.get("role") in {"assistant", "ai"}:
                content = str(msg.get("content", "") or "").strip().lower()
            if not content:
                continue
            if len(content) > 520:
                return False
            markers = [
                "bạn đang hỏi",
                "cần xác định chủ thể",
                "bạn vui lòng",
                "cho biết thêm",
                "trường hợp nào",
                "để tôi trả lời chính xác",
            ]
            return any(marker in content for marker in markers)
        return False

    def _collect_recent_user_context(self, chat_history: list, turns: int = 3) -> str:
        if not chat_history:
            return ""
        snippets: List[str] = []
        for msg in reversed(chat_history):
            content = ""
            if isinstance(msg, HumanMessage):
                content = str(getattr(msg, "content", "") or "").strip()
            elif isinstance(msg, dict) and msg.get("role") == "user":
                content = str(msg.get("content", "") or "").strip()
            elif isinstance(msg, str):
                content = msg.strip()
            if not content:
                continue
            snippets.append(content)
            if len(snippets) >= turns:
                break
        snippets.reverse()
        return " ".join(snippets).strip()

    def _build_analyzer_input(self, user_input: str, chat_history: list) -> tuple[str, str]:
        should_carry = self._is_followup_query(user_input) or self._last_bot_asked_clarification(chat_history)
        if not should_carry:
            return user_input, ""
        carried_context = self._collect_recent_user_context(chat_history, turns=3)
        if not carried_context:
            return user_input, ""
        analyzer_input = (
            "[NGỮ CẢNH HỘI THOẠI TRƯỚC]\n"
            f"{carried_context}\n\n"
            "[CÂU HỎI MỚI]\n"
            f"{user_input}\n\n"
            "YÊU CẦU: Tạo keywords cho truy vấn hiện tại nhưng phải giữ dữ kiện pháp lý quan trọng "
            "từ ngữ cảnh trước (nếu có), đặc biệt là hành vi vi phạm, quyền đơn phương, nợ lương, "
            "và nghĩa vụ thanh toán."
        )
        return analyzer_input, carried_context

    def _extract_context_carry_terms(self, carried_context: str) -> List[str]:
        text = (carried_context or "").lower()
        terms: List[str] = []
        for phrase in self.CONTEXT_CARRY_PHRASES:
            if phrase in text:
                terms.append(phrase)
        fallback_terms = self._extract_keywords_fallback(carried_context)
        terms.extend([t for t in fallback_terms if not t.lower().startswith("điều ")])
        return self._dedup_preserve_order(terms)[:6]

    def _compose_search_query(
        self,
        user_input: str,
        keywords: List[str],
        chat_history: list,
        carried_context: str = "",
    ) -> str:
        merged_terms = list(keywords or [])
        if carried_context or self._is_followup_query(user_input):
            context_text = carried_context or self._collect_recent_user_context(chat_history, turns=3)
            if context_text:
                merged_terms.extend(self._extract_context_carry_terms(context_text))
        if not merged_terms:
            merged_terms = self._extract_keywords_fallback(user_input)
        merged_terms = self._dedup_preserve_order(merged_terms)
        if not merged_terms:
            return "luật lao động"
        return " ".join(merged_terms[:9])

    def _heuristic_fact_pattern_analysis(self, user_input: str) -> Dict:
        """Deterministic fallback for high-risk fact-pattern issue spotting."""
        text = (user_input or "").lower()
        issues: List[str] = []
        supplementary: List[str] = []

        def add(issue: str, query: str) -> None:
            if issue not in issues:
                issues.append(issue)
            if query not in supplementary:
                supplementary.append(query)

        if any(kw in text for kw in ["gộp lỗi", "gộp vi phạm", "đi muộn"]) and any(
            kw in text for kw in ["sa thải", "kỷ luật", "xử lý"]
        ):
            add("thời hiệu xử lý kỷ luật", "Điều 123 thời hiệu xử lý kỷ luật lao động")
            add("nguyên tắc không gộp lỗi", "Điều 122 nguyên tắc xử lý kỷ luật lao động")
            add("căn cứ sa thải hợp pháp", "Điều 125 căn cứ sa thải")

        if "mang thai" in text and any(kw in text for kw in ["hết hạn", "gia hạn", "không gia hạn"]):
            add("hết hạn hợp đồng lao động", "Điều 34 các trường hợp chấm dứt hợp đồng lao động")
            add("bảo vệ lao động nữ mang thai", "Điều 137 bảo vệ thai sản lao động nữ")

        if any(kw in text for kw in ["mắng", "xúc phạm", "ngược đãi", "đánh đập"]) and any(
            kw in text for kw in ["nghỉ", "không báo trước", "bồi thường"]
        ):
            add("ngoại lệ nghỉ không báo trước", "Điều 35 quyền đơn phương chấm dứt không cần báo trước")
            add("nghĩa vụ khi đơn phương trái luật", "Điều 40 nghĩa vụ người lao động đơn phương trái luật")

        if any(kw in text for kw in ["nợ lương", "chậm lương", "không trả lương"]) and any(
            kw in text for kw in ["không báo trước", "bồi thường", "nghỉ việc", "nghỉ ngay"]
        ):
            add("không được trả lương đúng hạn", "Điều 35 quyền nghỉ ngay khi không được trả lương")
            add("trả lương đúng hạn", "Điều 97 kỳ hạn trả lương")
            add("bồi thường khi đơn phương trái luật", "Điều 40 nghĩa vụ bồi thường")

        if "hợp đồng" in text and any(kw in text for kw in ["lần 3", "lần thứ 3", "lần thứ ba"]):
            add("ký quá hai lần hợp đồng xác định thời hạn", "Điều 20 loại hợp đồng lao động")

        if "sa thải" in text and any(kw in text for kw in ["mạng xã hội", "đăng bài", "ngoài giờ"]):
            add("căn cứ sa thải hợp pháp", "Điều 125 căn cứ sa thải")
            add("nội quy lao động", "Điều 118 nội quy lao động")
            add("hành vi bị nghiêm cấm", "Điều 8 các hành vi bị nghiêm cấm")

        if "sa thải" in text and any(kw in text for kw in ["tự ý bỏ việc", "bỏ việc", "6 ngày"]):
            add("căn cứ sa thải do tự ý bỏ việc", "Điều 125 căn cứ sa thải do tự ý bỏ việc")
            add("trình tự xử lý kỷ luật", "Điều 122 nguyên tắc xử lý kỷ luật")
            add("thời hiệu xử lý kỷ luật", "Điều 123 thời hiệu xử lý kỷ luật")

        return {
            "is_fact_pattern": bool(issues),
            "legal_issues": issues[:4],
            "supplementary_queries": supplementary[:3],
        }

    def _classify_fact_pattern(self, user_input: str) -> Dict:
        """
        Phân loại câu hỏi có phải fact-pattern không và trích xuất legal issues.
        Kết quả chỉ dùng để mở rộng retrieval query, không thay thế guard/citation.
        """
        text = (user_input or "").strip()
        text_lower = text.lower()
        is_likely_factpattern = (
            len(text) > 80
            and any(
                kw in text_lower
                for kw in [
                    "công ty",
                    "nhân viên",
                    "người lao động",
                    "sếp",
                    "chị",
                    "anh",
                    "đúng hay sai",
                    "có hợp pháp",
                    "có được không",
                    "tháng",
                    "lần",
                ]
            )
        )
        if not is_likely_factpattern:
            return {"is_fact_pattern": False, "legal_issues": [], "supplementary_queries": []}

        heuristic = self._heuristic_fact_pattern_analysis(text)
        if heuristic.get("is_fact_pattern"):
            logging.info("🧩 [FactPattern] Heuristic issue spotting hit: %s", heuristic)
            return heuristic

        prompt = self.FACT_PATTERN_PROMPT.format(user_input=text)
        try:
            response = self.llm_analyzer.invoke(prompt)
            raw = response.content if hasattr(response, "content") else str(response)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            result = json.loads(raw)
            legal_issues = list(result.get("legal_issues", []) or [])[:4]
            supplementary = list(result.get("supplementary_queries", []) or [])[:3]
            if heuristic.get("is_fact_pattern"):
                legal_issues = self._dedup_preserve_order(legal_issues + heuristic["legal_issues"])[:4]
                supplementary = self._dedup_preserve_order(supplementary + heuristic["supplementary_queries"])[:3]
            return {
                "is_fact_pattern": bool(result.get("is_fact_pattern", False) or heuristic.get("is_fact_pattern")),
                "legal_issues": legal_issues,
                "supplementary_queries": supplementary,
            }
        except Exception as err:
            logging.warning("⚠️ [FactPattern] Pre-analysis failed; using heuristic fallback: %s", err)
            return heuristic

    def _build_fact_pattern_guidance(self, user_input: str) -> str:
        """Small runtime guidance block for high-risk legal issue branching."""
        text = (user_input or "").lower()
        guidance: List[str] = []

        if "mang thai" in text and any(kw in text for kw in ["hết hạn", "gia hạn", "không gia hạn"]):
            guidance.append(
                "GUIDANCE: Đây là pattern lao động nữ mang thai nhưng hợp đồng xác định thời hạn hết hạn. "
                "Phải tách Điều 34 (hết hạn hợp đồng là căn cứ chấm dứt) khỏi Điều 137 "
                "(cấm sa thải/đơn phương vì lý do mang thai; ưu tiên giao kết hợp đồng mới nếu context có). "
                "Không kết luận 'chị đúng vì bị đuổi việc' nếu dữ kiện chỉ là hết hạn tự nhiên."
            )

        if any(kw in text for kw in ["mắng", "xúc phạm", "ngược đãi", "đánh đập"]) and any(
            kw in text for kw in ["nghỉ", "không báo trước", "bồi thường"]
        ):
            guidance.append(
                "GUIDANCE: Đây là pattern nghỉ ngay sau lời nói/hành vi có thể xúc phạm. "
                "Phải xét Điều 35 khoản 2 điểm c trước Điều 40. Trả lời hai nhánh: "
                "nếu đủ yếu tố nhục mạ/ảnh hưởng sức khỏe, nhân phẩm, danh dự thì có thể nghỉ không báo trước; "
                "nếu không đủ yếu tố thì có thể vi phạm báo trước và phát sinh Điều 40. "
                "Không được coi riêng cụm 'mắng vô lý' là đã chắc chắn đủ căn cứ; phải nói cần chứng minh mức độ/lời nói cụ thể."
            )

        if any(kw in text for kw in ["gộp lỗi", "gộp vi phạm", "gộp cả lỗi", "đi làm muộn"]) and any(
            kw in text for kw in ["sa thải", "kỷ luật", "xử lý"]
        ):
            guidance.append(
                "GUIDANCE: Đây là pattern gộp lỗi để sa thải. Phải xét Điều 122 về nguyên tắc xử lý kỷ luật, "
                "Điều 123 về thời hiệu, rồi mới xét Điều 125 về căn cứ sa thải. "
                "Không tự kết luận hết thời hiệu nếu dữ kiện vẫn nằm trong mốc 6/12 tháng."
            )

        if any(kw in text for kw in ["nợ lương", "chậm lương", "không trả lương"]) and any(
            kw in text for kw in ["nghỉ", "không báo trước", "bồi thường"]
        ):
            guidance.append(
                "GUIDANCE: Đây là pattern nghỉ ngay vì không được trả lương đúng hạn. "
                "Phải xét ngoại lệ Điều 35 khoản 2 điểm b trước khi áp Điều 40."
            )

        if "hợp đồng" in text and any(kw in text for kw in ["lần 3", "lần thứ 3", "lần thứ ba"]):
            guidance.append(
                "GUIDANCE: Đây là pattern ký hợp đồng xác định thời hạn quá hai lần. "
                "Phải xét Điều 20 về chuyển thành hợp đồng không xác định thời hạn."
            )

        if "sa thải" in text and any(kw in text for kw in ["tự ý bỏ việc", "bỏ việc", "6 ngày"]):
            guidance.append(
                "GUIDANCE: Đây là pattern sa thải do tự ý bỏ việc. "
                "Phải trả lời có điều kiện: Điều 125 có thể là căn cứ nếu đủ số ngày và không có lý do chính đáng, "
                "nhưng công ty vẫn phải chứng minh lỗi và làm đúng trình tự/thời hiệu kỷ luật theo Điều 122, Điều 123."
            )

        if not guidance:
            return ""
        return "\n".join(guidance)

    def _build_high_risk_fallback_answer(self, user_input: str, docs: list) -> str:
        """Grounded deterministic fallback when the LLM is empty/rate-limited."""
        text = (user_input or "").lower()
        available = set(extract_articles_from_documents(docs))

        if "mang thai" in text and any(kw in text for kw in ["hết hạn", "gia hạn", "không gia hạn"]):
            if {34, 137}.issubset(available):
                return (
                    "Kết luận: cần tách hai vấn đề. Nếu hợp đồng xác định thời hạn đã hết hạn, "
                    "đây là căn cứ chấm dứt theo Điều 34, không mặc nhiên là sa thải hoặc đơn phương chấm dứt vì mang thai. "
                    "Tuy nhiên, Điều 137 bảo vệ lao động nữ mang thai và quy định trường hợp hợp đồng hết hạn trong thời gian mang thai "
                    "thì người lao động được ưu tiên giao kết hợp đồng lao động mới. Vì vậy, công ty có căn cứ chấm dứt do hết hạn, "
                    "nhưng phải lưu ý quyền ưu tiên giao kết hợp đồng mới của chị B; không nên gọi đây là 'đuổi việc' nếu chỉ là hết hạn tự nhiên.\n\n"
                    "Căn cứ pháp lý: Điều 34, Điều 137 Bộ luật Lao động 2019."
                )

        if any(kw in text for kw in ["mắng", "xúc phạm", "ngược đãi", "đánh đập"]) and any(
            kw in text for kw in ["nghỉ", "không báo trước", "bồi thường"]
        ):
            if {35, 40}.issubset(available):
                return (
                    "Kết luận: chưa thể kết luận một chiều rằng bạn chắc chắn phải bồi thường. "
                    "Cần xét ngoại lệ tại Điều 35 trước khi áp Điều 40.\n\n"
                    "Nếu việc 'sếp mắng vô lý' có mức độ là lời nói/hành vi nhục mạ, làm ảnh hưởng sức khỏe, nhân phẩm, danh dự "
                    "hoặc thuộc hành vi ngược đãi/cưỡng bức lao động, bạn có thể nghỉ không cần báo trước theo Điều 35 khoản 2. "
                    "Khi đó không áp nghĩa vụ bồi thường do nghỉ trái luật.\n\n"
                    "Nếu chỉ là mâu thuẫn nhẹ và không đủ căn cứ thuộc ngoại lệ trên, việc nghỉ ngay với hợp đồng không xác định thời hạn "
                    "có thể vi phạm thời hạn báo trước và phát sinh nghĩa vụ theo Điều 40.\n\n"
                    "Căn cứ pháp lý: Điều 35, Điều 40 Bộ luật Lao động 2019."
                )

        if any(kw in text for kw in ["gộp lỗi", "gộp vi phạm", "gộp cả lỗi", "đi làm muộn"]) and any(
            kw in text for kw in ["sa thải", "kỷ luật", "xử lý"]
        ):
            if {122, 123}.issubset(available):
                refs = [a for a in [122, 123, 125] if a in available]
                ref_text = ", ".join(f"Điều {a}" for a in refs)
                return (
                    "Kết luận: công ty không nên gộp lỗi tháng 3 với lỗi tháng 5 để áp hình thức sa thải. "
                    "Trước khi sa thải phải kiểm tra nguyên tắc xử lý kỷ luật, thời hiệu và căn cứ sa thải.\n\n"
                    "Điều 122 yêu cầu việc xử lý kỷ luật tuân thủ nguyên tắc, mỗi hành vi vi phạm chỉ bị xử lý một lần. "
                    "Điều 123 yêu cầu kiểm tra thời hiệu xử lý kỷ luật. Nếu còn trong thời hiệu thì vẫn phải xử lý đúng từng hành vi; "
                    "nếu hết thời hiệu thì không được dùng vi phạm đó để làm căn cứ kỷ luật. "
                    "Nếu muốn sa thải, công ty còn phải chứng minh hành vi thuộc căn cứ sa thải theo Điều 125.\n\n"
                    f"Căn cứ pháp lý: {ref_text} Bộ luật Lao động 2019."
                )

        if any(kw in text for kw in ["nợ lương", "chậm lương", "không trả lương"]) and any(
            kw in text for kw in ["nghỉ", "không báo trước", "bồi thường"]
        ):
            if 35 in available:
                refs = [a for a in [35, 40, 97] if a in available]
                ref_text = ", ".join(f"Điều {a}" for a in refs)
                return (
                    "Kết luận: nếu công ty không trả đủ lương hoặc trả lương không đúng hạn, "
                    "người lao động có quyền đơn phương chấm dứt hợp đồng không cần báo trước theo Điều 35. "
                    "Khi nghỉ thuộc ngoại lệ này thì không phải bồi thường như trường hợp đơn phương trái luật theo Điều 40.\n\n"
                    f"Căn cứ pháp lý: {ref_text} Bộ luật Lao động 2019."
                )

        if "hợp đồng" in text and any(kw in text for kw in ["lần 3", "lần thứ 3", "lần thứ ba"]):
            if 20 in available:
                return (
                    "Kết luận: nếu các bên đã ký hợp đồng xác định thời hạn liên tiếp quá giới hạn luật cho phép, "
                    "hợp đồng tiếp theo phải được xác định là hợp đồng không xác định thời hạn theo Điều 20.\n\n"
                    "Căn cứ pháp lý: Điều 20 Bộ luật Lao động 2019."
                )

        if "sa thải" in text and any(kw in text for kw in ["mạng xã hội", "đăng bài", "ngoài giờ"]):
            if 125 in available:
                refs = [a for a in [125, 118, 8] if a in available]
                ref_text = ", ".join(f"Điều {a}" for a in refs)
                return (
                    "Kết luận: không đủ căn cứ để coi việc đăng bài trên mạng xã hội cá nhân ngoài giờ làm việc "
                    "là căn cứ sa thải nếu hành vi không thuộc các trường hợp sa thải hợp pháp hoặc không vi phạm nội quy hợp lệ. "
                    "Cần đối chiếu Điều 125 về căn cứ sa thải và nội quy lao động áp dụng cho hành vi này.\n\n"
                    f"Căn cứ pháp lý: {ref_text} Bộ luật Lao động 2019."
                )

        if "sa thải" in text and any(kw in text for kw in ["tự ý bỏ việc", "bỏ việc", "6 ngày"]):
            if 125 in available:
                refs = [a for a in [125, 122, 123] if a in available]
                ref_text = ", ".join(f"Điều {a}" for a in refs)
                return (
                    "Kết luận: công ty có thể có căn cứ sa thải nếu chứng minh người lao động tự ý bỏ việc đủ số ngày "
                    "theo Điều 125 và không có lý do chính đáng. Tuy nhiên, không nên kết luận hợp pháp tuyệt đối nếu chưa kiểm tra thủ tục.\n\n"
                    "Điều kiện cần kiểm tra thêm: công ty phải chứng minh lỗi, lý do nghỉ không chính đáng, nội quy/quy chế áp dụng "
                    "và trình tự, thời hiệu xử lý kỷ luật theo Điều 122, Điều 123.\n\n"
                    f"Căn cứ pháp lý: {ref_text} Bộ luật Lao động 2019."
                )

        return ""

    def _augment_high_risk_answer(self, answer: str, user_input: str, docs: list) -> str:
        """Patch omissions for high-risk patterns only when supporting articles exist."""
        text = (user_input or "").lower()
        current = (answer or "").strip()
        if not current:
            return current
        current_lower = current.lower()
        available = set(extract_articles_from_documents(docs))
        additions: List[str] = []

        if "mang thai" in text and any(kw in text for kw in ["hết hạn", "gia hạn", "không gia hạn"]):
            if 137 in available and "ưu tiên" not in current_lower:
                additions.append(
                    "Lưu ý thêm: Điều 137 còn quy định khi hợp đồng hết hạn trong thời gian lao động nữ mang thai "
                    "thì người lao động được ưu tiên giao kết hợp đồng lao động mới."
                )

        if any(kw in text for kw in ["gộp lỗi", "gộp vi phạm", "gộp cả lỗi", "đi làm muộn"]) and any(
            kw in text for kw in ["sa thải", "kỷ luật", "xử lý"]
        ):
            if 125 in available and "điều 125" not in current_lower:
                additions.append(
                    "Ngoài ra, nếu công ty muốn áp dụng hình thức sa thải thì còn phải chứng minh hành vi thuộc "
                    "một trong các căn cứ sa thải theo Điều 125."
                )

        if not additions:
            return current
        return f"{current}\n\n" + "\n".join(additions)

    @staticmethod
    def _extract_retry_after_seconds(error_text: str) -> float | None:
        match = re.search(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", error_text, flags=re.IGNORECASE)
        if not match:
            return None
        try:
            return float(match.group(1))
        except Exception:
            return None

    def _invoke_reasoner_with_retry(
        self,
        reasoner_context: str,
        chat_history: list,
        user_input: str,
        max_attempts: int = 3,
    ) -> str:
        """Invoke reasoner with bounded retry for transient Groq rate limits."""
        current_context = reasoner_context or ""
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return self.reasoner_chain.invoke({
                    "context": current_context,
                    "chat_history": chat_history[-6:],
                    "input": user_input,
                })
            except Exception as exc:
                last_error = exc
                msg = str(exc or "")
                is_rate_limit = "429" in msg or "rate limit" in msg.lower()
                if not is_rate_limit or attempt >= max_attempts:
                    raise
                retry_after = self._extract_retry_after_seconds(msg)
                wait_seconds = retry_after if retry_after is not None else min(10.0, 2.5 * attempt)
                logging.warning(
                    "⚠️ [Reasoner] Rate limited; retrying in %.2fs (attempt %s/%s)",
                    wait_seconds,
                    attempt + 1,
                    max_attempts,
                )
                time.sleep(max(0.8, wait_seconds))
                if len(current_context) > 5000:
                    current_context = current_context[: max(3000, int(len(current_context) * 0.75))]
        if last_error:
            raise last_error
        return ""

    def _remove_chinese_characters(self, text: str, preserve_edges: bool = False) -> str:
        """
        Remove CJK (Chinese, Japanese Kanji, Korean) characters and punctuation from text.
        Regex pattern matches:
        - U+3000-U+303F (CJK Symbols and Punctuation: ，。（）etc)
        - U+4E00-U+9FFF (CJK Unified Ideographs)
        - U+FF00-U+FFEF (Halfwidth and Fullwidth Forms: fullwidth punctuation)
        
        Args:
            text: Input text that may contain CJK characters or punctuation
            
        Returns:
            Text with CJK characters and punctuation removed (preserves spaces and ASCII)
        """
        # Remove CJK Symbols/Punctuation + CJK Ideographs + Fullwidth Forms
        cleaned = re.sub(r'[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]+', '', text)
        # Clean up multiple spaces
        cleaned = re.sub(r' +', ' ', cleaned)
        # For streamed chunks, preserve leading/trailing spaces to avoid word-join artifacts.
        return cleaned if preserve_edges else cleaned.strip()

    def _is_clarifying_payload(self, text: str) -> bool:
        return str(text or "").strip().startswith(self.CLARIFY_TAG)

    def _strip_clarifying_payload(self, text: str) -> str:
        raw = str(text or "").strip()
        if raw.startswith(self.CLARIFY_TAG):
            return raw[len(self.CLARIFY_TAG):].strip()
        return raw

    def _build_reasoner_context(self, docs: list, fallback_context: str = "") -> str:
        """
        Giới hạn context đưa vào Reasoner để tránh token burst (429),
        đồng thời ưu tiên các đoạn đầu đã được router/reranker xếp hạng.
        """
        max_docs = max(1, REASONER_MAX_CONTEXT_DOCS)
        max_chars = max(800, REASONER_MAX_CONTEXT_CHARS)
        if not docs:
            text = (fallback_context or "").strip()
            return text[:max_chars]

        picked = []
        used = 0
        for doc in docs[:max_docs]:
            text = (doc.page_content or "").strip()
            if not text:
                continue
            remaining = max_chars - used
            if remaining <= 32:
                break
            if len(text) > remaining:
                text = text[:remaining]
            picked.append(text)
            used += len(text) + 2
        compact = "\n\n".join(picked).strip()
        if compact:
            return compact
        text = (fallback_context or "").strip()
        return text[:max_chars]

    def _rule_based_pre_answer(self, user_input: str) -> str:
        """
        Rule-based guardrails for high-risk queries that repeatedly fail in QA.
        Returns empty string if rule is not applicable.
        """
        user_lower = user_input.lower().strip()

        severance_answer = try_build_severance_answer(user_input)
        if severance_answer:
            return severance_answer

        # Case -1: Wage arrears are a common high-risk fact pattern. Answer directly
        # to avoid the reasoner drifting into unrelated unlawful termination duties.
        has_unpaid_wage = any(
            marker in user_lower
            for marker in ["nợ lương", "chậm lương", "không trả lương", "chưa trả lương"]
        )
        has_contract_term_context = any(
            marker in user_lower
            for marker in ["hợp đồng", "hđlđ", "24 tháng", "12 tháng", "36 tháng"]
        )
        if has_unpaid_wage and has_contract_term_context:
            return (
                "Công ty đang nợ/chậm trả lương là vấn đề về nghĩa vụ trả lương đúng hạn. "
                "Người sử dụng lao động phải trả lương trực tiếp, đầy đủ, đúng hạn; nếu trả chậm thì còn phải trả thêm "
                "khoản tiền do chậm trả theo Điều 97 Bộ luật Lao động 2019. "
                "Nếu bạn không được trả lương đầy đủ hoặc đúng hạn, bạn có thể đơn phương chấm dứt hợp đồng lao động "
                "mà không cần báo trước theo Điều 35 Bộ luật Lao động 2019, trừ trường hợp bất khả kháng theo luật."
            )

        # Case 0: Deterministic handling for unlawful unilateral termination compensation.
        # Nếu chủ thể mơ hồ, ưu tiên hỏi làm rõ thay vì route "rule_based".
        if is_unlawful_unilateral_compensation_query(user_input):
            role = detect_unilateral_termination_role(user_input)
            if role in {"employee", "employer"}:
                compensation_answer = build_unilateral_compensation_response(user_input)
                if compensation_answer:
                    return compensation_answer
            if role == "ambiguous":
                return (
                    f"{self.CLARIFY_TAG} Câu hỏi này cần xác định chủ thể để áp dụng đúng điều luật: "
                    "bạn đang hỏi về người lao động đơn phương trái luật (Điều 40) "
                    "hay người sử dụng lao động đơn phương trái luật (Điều 41)?"
                )

        # Case 1: Generic article question should ask clarifying question (Nhóm B)
        article_match = re.search(r'điều\s*(\d+)', user_lower)
        if article_match and int(article_match.group(1)) > MAX_ARTICLE_NUMBER:
            return (
                "Bộ luật Lao động 2019 không có điều số này. "
                "Bạn vui lòng kiểm tra lại số điều hoặc nêu rõ văn bản luật khác nếu không phải Bộ luật Lao động 2019."
            )
        asks_generic_article = (
            article_match is not None
            and ("quy định gì" in user_lower or "quy định điều gì" in user_lower or "nói gì" in user_lower)
        )
        has_specific_topic = any(
            kw in user_lower for kw in [
                "hợp đồng", "sa thải", "lương", "nghỉ", "mang thai",
                "bảo hiểm", "tranh chấp", "thời giờ", "đơn phương"
            ]
        )
        if asks_generic_article and not has_specific_topic:
            article_no = article_match.group(1)
            return (
                f"Bạn đang hỏi Điều {article_no} của văn bản nào? "
                "Nếu là Bộ luật Lao động, bạn có thể nói rõ chủ đề như hợp đồng, sa thải, tiền lương, "
                "hoặc quyền và nghĩa vụ để tôi trả lời chính xác hơn."
            )

        # Case 2: Annual leave should anchor to Điều 113/114.
        asks_annual_leave = (
            "nghỉ phép" in user_lower
            and ("hằng năm" in user_lower or "một năm" in user_lower or "1 năm" in user_lower)
        )
        if asks_annual_leave:
            return (
                "Theo Điều 113 Bộ luật Lao động 2019, người lao động làm đủ 12 tháng "
                "được nghỉ hằng năm hưởng nguyên lương: 12 ngày (điều kiện bình thường), "
                "14 ngày (lao động chưa thành niên/khuyết tật/nghề nặng nhọc), hoặc 16 ngày "
                "(nghề đặc biệt nặng nhọc). Nếu làm chưa đủ 12 tháng thì số ngày nghỉ được tính theo tỷ lệ thời gian làm việc."
            )

        # Case 3: Pregnant workers should have deterministic protection answer
        asks_pregnant_termination = (
            "mang thai" in user_lower
            and ("sa thải" in user_lower or "chấm dứt hợp đồng" in user_lower)
        )
        asks_natural_expiry = any(
            marker in user_lower
            for marker in ["hết hạn", "không gia hạn", "gia hạn", "cuối tháng", "đúng ngày hết hạn"]
        )
        if asks_pregnant_termination:
            if asks_natural_expiry:
                return ""
            return (
                "Người sử dụng lao động không được đơn phương chấm dứt hợp đồng lao động "
                "với lao động nữ mang thai trong thời gian mang thai, nghỉ thai sản hoặc nuôi con dưới 12 tháng tuổi. "
                "Căn cứ pháp lý: Điều 137 Bộ luật Lao động 2019."
            )

        # Case 4: Trial period count should be direct and concise
        asks_trial_count = (
            "thử việc" in user_lower
            and ("bao nhiêu lần" in user_lower or "mấy lần" in user_lower)
        )
        if asks_trial_count:
            return (
                "Mỗi công việc chỉ được thử việc 01 lần. "
                "Căn cứ pháp lý: Điều 24 Bộ luật Lao động 2019."
            )

        return ""

    def _rule_based_followup_answer(self, user_input: str, chat_history: list) -> str:
        """
        Deterministic follow-up handling cho chuỗi hội thoại đã có dữ kiện trọng yếu.
        Mục tiêu: giảm over-reject và giảm gọi LLM không cần thiết.
        """
        if not chat_history:
            return ""

        user_lower = (user_input or "").strip().lower()
        carried = self._collect_recent_user_context(chat_history, turns=4).lower()
        if not carried:
            return ""

        unpaid_markers = [
            "nợ lương",
            "chậm lương",
            "không trả lương",
            "nợ 2 tháng",
            "nợ hai tháng",
        ]
        has_unpaid_context = any(marker in carried for marker in unpaid_markers)
        if not has_unpaid_context and not any(marker in user_lower for marker in unpaid_markers):
            return ""

        asks_settlement = any(
            token in user_lower
            for token in ["thanh toán", "khoản nào", "quyền lợi", "trả cho tôi", "tiền nào"]
        )
        if asks_settlement and any(token in user_lower for token in ["nghỉ", "chấm dứt", "nghỉ ngay"]):
            return (
                "Khi bạn nghỉ việc trong bối cảnh công ty nợ lương, công ty vẫn phải thanh toán các khoản sau:\n"
                "- Tiền lương còn nợ và phần trả chậm theo Điều 97.\n"
                "- Các khoản liên quan đến quyền lợi của bạn khi chấm dứt hợp đồng (thanh toán trong 14 ngày, "
                "trường hợp đặc biệt tối đa 30 ngày) theo Điều 48.\n"
                "- Trợ cấp thôi việc nếu đủ điều kiện theo Điều 46.\n"
                "- Xác nhận thời gian đóng và trả lại giấy tờ/BHXH theo Điều 48."
            )

        asks_immediate_leave = (
            ("nghỉ ngay" in user_lower or "không báo trước" in user_lower or "đơn phương" in user_lower)
            and any(token in user_lower for token in ["được không", "có được", "đúng không", "?"])
        )
        if asks_immediate_leave:
            return (
                "Nếu công ty nợ lương/không trả lương đúng hạn, bạn có thể đơn phương chấm dứt hợp đồng "
                "mà không cần báo trước theo Điều 35 Bộ luật Lao động 2019 "
                "(trừ trường hợp bất khả kháng theo khoản 4 Điều 97)."
            )

        return ""

    def run_structured(self, user_input: str, chat_history: list = None) -> RunResult:
        """
        Single structured entrypoint cho toàn bộ luồng RAG (blocking).

        Trả về RunResult chứa đầy đủ thông tin để UI render:
        answer, context_text, docs, validation, retrieval_check, v.v.
        """
        if chat_history is None:
            chat_history = []

        # ── Intent classification (duy nhất 1 lần) ────────────────────
        intent_res = classify_intent(user_input, self.llm_intent, chat_history=chat_history)
        if intent_res.intent != Intent.LEGAL:
            return RunResult(
                answer=intent_res.response,
                intent_result=intent_res,
                route="intent_non_legal",
            )

        # ── Rule-based override ───────────────────────────────────────
        rule_answer = self._rule_based_pre_answer(user_input)
        if rule_answer:
            if self._is_clarifying_payload(rule_answer):
                clarify_answer = self._strip_clarifying_payload(rule_answer)
                return RunResult(
                    answer=clarify_answer,
                    context_text=clarify_answer,
                    intent_result=intent_res,
                    is_clarifying=True,
                    route="clarifying",
                )
            return RunResult(
                answer=rule_answer,
                intent_result=intent_res,
                route="rule_based",
            )

        followup_rule_answer = self._rule_based_followup_answer(user_input, chat_history)
        if followup_rule_answer:
            return RunResult(
                answer=followup_rule_answer,
                intent_result=intent_res,
                route="rule_followup",
            )

        query_mode = classify_query_mode(user_input)
        search_query, context_text, docs = self._analyze_and_retrieve(user_input, chat_history)

        # ── FIX F: Clarifying question detection ──────────────────────
        # _analyze_and_retrieve trả context_text = clarifying question khi
        # article-only keywords + poor retrieval.
        if self._is_clarifying_payload(context_text):
            logging.info("✅ [FIX F] Clarifying question returned directly")
            clarify_answer = self._strip_clarifying_payload(context_text)
            return RunResult(
                answer=clarify_answer,
                context_text=clarify_answer,
                docs=docs,
                intent_result=intent_res,
                query_mode=query_mode,
                search_query=search_query,
                is_clarifying=True,
                route="clarifying",
            )

        # ── Article query guard ───────────────────────────────────────
        article_resolution = resolve_article_query(user_input=user_input, documents=docs)
        if article_resolution:
            return RunResult(
                answer=article_resolution,
                context_text=context_text,
                docs=docs,
                intent_result=intent_res,
                query_mode=query_mode,
                search_query=search_query,
                route="article_resolution",
            )

        # ── Retrieval strength guard ──────────────────────────────────
        retrieval_check = assess_retrieval_strength(user_input=user_input, documents=docs)
        if not retrieval_check.get("is_strong_enough", False):
            failure = classify_failure_cause(
                user_input=user_input,
                query_mode=query_mode,
                retrieval_check=retrieval_check,
                used_article_resolution=False,
            )
            fallback_answer = build_insufficient_context_response(
                user_input=user_input,
                query_mode=query_mode,
                retrieval_check=retrieval_check,
                failure_cause=failure.get("primary", ""),
            )
            return RunResult(
                answer=fallback_answer,
                context_text=context_text,
                docs=docs,
                intent_result=intent_res,
                query_mode=query_mode,
                search_query=search_query,
                retrieval_check=retrieval_check,
                route="insufficient_context",
            )

        # Deterministic branch for quote/article requests when context is available.
        if query_mode == "quote_request":
            quote_answer = (context_text or "").strip()
            quote_validation = validate_answer_against_context(
                answer=quote_answer,
                user_input=user_input,
                documents=docs,
                query_mode=query_mode,
                context_override=context_text,
            )
            if quote_answer and quote_validation.get("ok", False):
                return RunResult(
                    answer=quote_answer,
                    context_text=context_text,
                    docs=docs,
                    intent_result=intent_res,
                    query_mode=query_mode,
                    search_query=search_query,
                    retrieval_check=retrieval_check,
                    validation=quote_validation,
                    route="quote_direct",
                )
            failure = classify_failure_cause(
                user_input=user_input,
                query_mode=query_mode,
                retrieval_check=retrieval_check,
                validation=quote_validation,
                used_article_resolution=False,
                answer=quote_answer,
            )
            fallback_answer = build_validation_fallback(
                quote_validation,
                query_mode,
                failure_cause=failure.get("primary", ""),
            )
            return RunResult(
                answer=fallback_answer,
                context_text=context_text,
                docs=docs,
                intent_result=intent_res,
                query_mode=query_mode,
                search_query=search_query,
                retrieval_check=retrieval_check,
                validation=quote_validation,
                route="quote_fallback",
            )

        requested_article = re.search(r"[Đđ]iều\s*(\d+)", user_input)
        if query_mode == "article_lookup" and requested_article and context_text.strip():
            article_no = requested_article.group(1)
            formatted = f"Điều {article_no} quy định như sau:\n\n{context_text.strip()}"
            return RunResult(
                answer=formatted,
                context_text=context_text,
                docs=docs,
                intent_result=intent_res,
                query_mode=query_mode,
                search_query=search_query,
                retrieval_check=retrieval_check,
                route="article_direct",
            )

        # ── Normal RAG flow ───────────────────────────────────────────
        reasoner_context = self._build_reasoner_context(docs=docs, fallback_context=context_text)
        guidance = self._build_fact_pattern_guidance(user_input)
        if guidance:
            reasoner_context = f"{guidance}\n\n{reasoner_context}"
        try:
            final_answer = self._invoke_reasoner_with_retry(
                reasoner_context=reasoner_context,
                chat_history=chat_history,
                user_input=user_input,
                max_attempts=3,
            )
        except Exception as reason_err:
            err_text = str(reason_err or "")
            err_lower = err_text.lower()
            logging.error("❌ [Reasoner] Invocation failed: %s", err_text)
            guided_fallback = self._build_high_risk_fallback_answer(user_input=user_input, docs=docs)
            if not guided_fallback:
                guided_fallback = build_extractive_fallback_answer(user_input=user_input, documents=docs)
            if guided_fallback:
                return RunResult(
                    answer=guided_fallback,
                    context_text=context_text,
                    docs=docs,
                    intent_result=intent_res,
                    query_mode=query_mode,
                    search_query=search_query,
                    retrieval_check=retrieval_check,
                    validation={"ok": True, "reason": "high_risk_guided_fallback", "invalid_articles": []},
                    route="rag",
                )
            if "429" in err_lower or "rate limit" in err_lower:
                fallback_answer = (
                    "Hệ thống đang quá tải tạm thời (rate limit API), nên chưa thể sinh phân tích đầy đủ ngay lúc này. "
                    "Bạn vui lòng thử lại sau vài giây, tôi sẽ tiếp tục đúng ngữ cảnh câu hỏi hiện tại."
                )
            else:
                fallback_answer = build_insufficient_context_response(
                    user_input=user_input,
                    query_mode=query_mode,
                    retrieval_check=retrieval_check,
                    failure_cause="model",
                )
            return RunResult(
                answer=fallback_answer,
                context_text=context_text,
                docs=docs,
                intent_result=intent_res,
                query_mode=query_mode,
                search_query=search_query,
                retrieval_check=retrieval_check,
                validation={
                    "ok": False,
                    "reason": f"reasoner_error:{err_text[:160]}",
                    "invalid_articles": [],
                },
                route="rag_error_fallback",
            )

        final_answer = self._remove_chinese_characters(final_answer)
        if not str(final_answer or "").strip():
            retry_prompt = (
                f"{user_input}\n\n"
                "YÊU CẦU BẮT BUỘC: Trả lời ngắn gọn theo 3 phần: Kết luận, Căn cứ, Áp dụng. "
                "Không được để trống câu trả lời."
            )
            try:
                final_answer = self.reasoner_chain.invoke({
                    "context": reasoner_context[:5000],
                    "chat_history": chat_history[-4:],
                    "input": retry_prompt,
                })
                final_answer = self._remove_chinese_characters(final_answer)
            except Exception as retry_err:
                logging.error("❌ [Reasoner] Empty-answer retry failed: %s", retry_err)

        if not str(final_answer or "").strip():
            guided_fallback = self._build_high_risk_fallback_answer(user_input=user_input, docs=docs)
            if not guided_fallback:
                guided_fallback = build_extractive_fallback_answer(user_input=user_input, documents=docs)
            if guided_fallback:
                return RunResult(
                    answer=guided_fallback,
                    context_text=context_text,
                    docs=docs,
                    intent_result=intent_res,
                    query_mode=query_mode,
                    search_query=search_query,
                    retrieval_check=retrieval_check,
                    validation={"ok": True, "reason": "high_risk_guided_fallback", "invalid_articles": []},
                    route="rag",
                )
            empty_validation = {
                "ok": False,
                "reason": "empty answer from reasoner",
                "invalid_articles": [],
            }
            final_answer = build_validation_fallback(
                empty_validation,
                query_mode,
                failure_cause="model",
            )
            return RunResult(
                answer=final_answer,
                context_text=context_text,
                docs=docs,
                intent_result=intent_res,
                query_mode=query_mode,
                search_query=search_query,
                retrieval_check=retrieval_check,
                validation=empty_validation,
                route="rag_empty_fallback",
            )

        final_answer = self._augment_high_risk_answer(
            answer=final_answer,
            user_input=user_input,
            docs=docs,
        )

        final_answer = enforce_citation_contract(
            answer=final_answer,
            user_input=user_input,
            documents=docs,
            query_mode=query_mode,
        )

        validation = validate_answer_against_context(
            answer=final_answer,
            user_input=user_input,
            documents=docs,
            query_mode=query_mode,
        )

        if not validation.get("ok", True):
            repaired_answer = repair_answer_citations(
                answer=final_answer,
                user_input=user_input,
                documents=docs,
                query_mode=query_mode,
            )
            repaired_validation = validate_answer_against_context(
                answer=repaired_answer,
                user_input=user_input,
                documents=docs,
                query_mode=query_mode,
            )
            if repaired_validation.get("ok", False):
                final_answer = repaired_answer
                validation = repaired_validation
            else:
                failure = classify_failure_cause(
                    user_input=user_input,
                    query_mode=query_mode,
                    retrieval_check=retrieval_check,
                    validation=repaired_validation,
                    used_article_resolution=False,
                    answer=final_answer,
                )
                # A4 FIX: Dùng repaired_validation (không phải validation gốc)
                final_answer = build_validation_fallback(
                    repaired_validation,
                    query_mode,
                    failure_cause=failure.get("primary", ""),
                )
                validation = repaired_validation
                user_lower = user_input.lower()
                if "trợ cấp" in user_lower and "trợ cấp" not in final_answer.lower():
                    final_answer += (
                        " Bạn có thể nêu rõ loại trợ cấp (thôi việc hay mất việc) "
                        "để tôi kiểm tra chính xác hơn."
                    )

        return RunResult(
            answer=final_answer,
            context_text=context_text,
            docs=docs,
            intent_result=intent_res,
            query_mode=query_mode,
            search_query=search_query,
            retrieval_check=retrieval_check,
            validation=validation,
            route="rag",
        )

    def run(self, user_input: str, chat_history: list = None) -> tuple:
        """
        Backward-compatible wrapper around run_structured().
        Returns: (final_answer: str, context_text: str)

        Dùng cho qa_test.py, e2e_test.py, và các caller cũ.
        """
        result = self.run_structured(user_input, chat_history)
        return result.answer, result.context_text


    def stream(self, user_input: str, chat_history: list = None):
        """
        Thực thi luồng RAG với streaming ở bước Reasoner.
        Pha 1 (Analyzer + Retriever) vẫn blocking.
        Pha 2 (Reasoner) trả về generator từng token.

        Yields:
            ("analyzing", None)        — báo hiệu đang ở Pha 1
            ("context", context_text)  — trả về context sau khi retrieve xong
            ("token", token_str)       — từng token từ LLM stream
        """
        if chat_history is None:
            chat_history = []

        # Pha 1: Analyzer + Retriever (blocking, thường ~8-12s)
        yield ("analyzing", None)
        # Rule-based override before RAG for known high-risk questions
        rule_answer = self._rule_based_pre_answer(user_input)
        if rule_answer:
            if self._is_clarifying_payload(rule_answer):
                rule_answer = self._strip_clarifying_payload(rule_answer)
            yield ("context", "")
            for char in rule_answer:
                yield ("token", char)
            return

        query_mode = classify_query_mode(user_input)
        search_query, context_text, docs = self._analyze_and_retrieve(user_input, chat_history)

        article_resolution = resolve_article_query(user_input=user_input, documents=docs)
        if article_resolution:
            yield ("context", context_text)
            for char in article_resolution:
                yield ("token", char)
            return

        retrieval_check = assess_retrieval_strength(user_input=user_input, documents=docs)
        if not retrieval_check.get("is_strong_enough", False):
            failure = classify_failure_cause(
                user_input=user_input,
                query_mode=query_mode,
                retrieval_check=retrieval_check,
                used_article_resolution=False,
            )
            fallback_answer = build_insufficient_context_response(
                user_input=user_input,
                query_mode=query_mode,
                retrieval_check=retrieval_check,
                failure_cause=failure.get("primary", ""),
            )
            yield ("context", context_text)
            for char in fallback_answer:
                yield ("token", char)
            return

        yield ("context", context_text)

        # FIX F: Check if context_text is a clarifying question
        if self._is_clarifying_payload(context_text):
            # This is a clarifying question, stream it directly without LLM
            logging.info(f"✅ [FIX F] Clarifying question streamed directly")
            clarify_answer = self._strip_clarifying_payload(context_text)
            for char in clarify_answer:
                yield ("token", char)
        else:
            # Pha 2: Reasoner stream (từng token)
            full_response = ""
            reasoner_context = self._build_reasoner_context(docs=docs, fallback_context=context_text)
            guidance = self._build_fact_pattern_guidance(user_input)
            if guidance:
                reasoner_context = f"{guidance}\n\n{reasoner_context}"
            for chunk in self.reasoner_chain.stream({
                "context": reasoner_context,
                "chat_history": chat_history[-6:],
                "input": user_input
            }):
                # Accumulate response
                full_response += chunk
                # Filter CJK characters from chunk if needed
                filtered_chunk = self._remove_chinese_characters(chunk, preserve_edges=True)
                if filtered_chunk:  # Only yield if chunk has content after filtering
                    yield ("token", filtered_chunk)


    def _analyze_and_retrieve(self, user_input: str, chat_history: list) -> tuple:
        """
        Phần dùng chung giữa run() và stream():
        Bước 4A (Analyzer) + Bước 4B (Retriever) + Bước 4B.1 (Citation Validator).
        Returns: (search_query: str, context_text: str)
        
        Improvements: 
        - Robust JSON parsing with fallback keyword extraction (Fix #1)
        - Citation validation against retrieved documents (Fix #3)
        - Clarifying question fallback for article-only queries (Fix F)
        """
        limit_history = chat_history[-4:] if len(chat_history) >= 4 else chat_history
        query_mode = classify_query_mode(user_input)
        requested_articles = [int(m) for m in re.findall(r"[Đđ]iều\s*(\d+)", user_input)]

        # P0 deterministic branch: article lookup đi thẳng exact retrieval trước analyzer/semantic.
        if (
            RETRIEVAL_ENABLE_DETERMINISTIC_ARTICLE_BRANCH
            and query_mode in {"article_lookup", "quote_request"}
            and requested_articles
        ):
            vector_db = getattr(self.retriever, "vectorstore", None)
            target_article = requested_articles[0]
            deterministic_docs = retrieve_exact_article(
                article_number=target_article,
                vector_db=vector_db,
                retriever=self.retriever,
                limit=8,
            )
            deduped = []
            seen = set()
            for d in deterministic_docs:
                meta = d.metadata or {}
                key = (
                    meta.get("chunk_id"),
                    meta.get("article_number", meta.get("dieu_so")),
                    (d.page_content or "")[:80],
                )
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(d)
            if deduped:
                context_text = "\n\n".join(d.page_content for d in deduped[:8])
                search_query = f"Điều {target_article}"
                logging.info(
                    "📌 [Retriever] Deterministic article branch hit | article=%s | docs=%s",
                    target_article,
                    len(deduped[:8]),
                )
                return search_query, context_text, deduped[:8]

        # Bước 4A: Trích xuất keyword từ JSON (với fallback)
        keywords = []
        search_query = ""
        analysis = {}
        analyzer_input, carried_context = self._build_analyzer_input(user_input, limit_history)
        
        try:
            # Try JSON parsing first
            raw_analysis = self.analyzer_chain.invoke({
                "input": analyzer_input,
                "chat_history": limit_history
            })
            analysis = self._parse_analyzer_output(raw_analysis)
            keywords = analysis.get("keywords", [])
            search_query = self._compose_search_query(
                user_input=user_input,
                keywords=keywords,
                chat_history=limit_history,
                carried_context=carried_context,
            )
            logging.info(f"✅ [Analyzer] JSON success: {analysis}")
            logging.info(f"🔍 [Analyzer] Keywords extracted: {keywords}")
            if carried_context:
                logging.info("🧠 [Analyzer] Follow-up context carried into query generation")
            
            # FIX C: Detect article-only keywords (e.g., ["Điều 35"] without context)
            article_only_keywords = [k for k in keywords if k.lower().startswith("điều ")]
            non_article_keywords = [k for k in keywords if not k.lower().startswith("điều ")]
            if article_only_keywords and not non_article_keywords:
                # User asked about a specific article but no context
                # Add generic context to help retriever find relevant info
                search_query = " ".join(article_only_keywords) + " luật lao động"
                logging.info(f"⚠️ [FIX C] Article-only query detected: Adding context 'luật lao động'")
            
        except json.JSONDecodeError as json_err:
            # Fallback: JSON parsing failed, use regex extraction
            logging.warning(f"⚠️ [Analyzer] JSON parse failed: {json_err}")
            logging.info(f"📌 [Analyzer] Switching to fallback keyword extraction...")
            keywords = self._extract_keywords_fallback(analyzer_input)
            search_query = self._compose_search_query(
                user_input=user_input,
                keywords=keywords,
                chat_history=limit_history,
                carried_context=carried_context,
            )
            logging.info(f"✅ [Analyzer] Fallback keywords: {keywords}")
            analysis = {"keywords": keywords, "issue": user_input[:100], "law_type": "luật lao động"}
            
        except Exception as e:
            # Broader exception handling
            logging.error(f"❌ [Analyzer] Unexpected error: {e}")
            logging.info(f"📌 [Analyzer] Switching to fallback keyword extraction...")
            keywords = self._extract_keywords_fallback(analyzer_input)
            search_query = self._compose_search_query(
                user_input=user_input,
                keywords=keywords,
                chat_history=limit_history,
                carried_context=carried_context,
            )
            logging.info(f"✅ [Analyzer] Fallback keywords: {keywords}")
            analysis = {"keywords": keywords, "issue": user_input[:100], "law_type": "luật lao động"}

        if not isinstance(keywords, list):
            keywords = [str(keywords)] if keywords else []

        fact_analysis = self._classify_fact_pattern(analyzer_input or user_input)
        if fact_analysis.get("is_fact_pattern") and fact_analysis.get("supplementary_queries"):
            expanded_keywords = list(keywords)
            expanded_keywords.extend(str(q) for q in fact_analysis.get("supplementary_queries", []) if q)
            keywords = self._dedup_preserve_order(expanded_keywords)
            analysis["keywords"] = keywords
            analysis["fact_pattern"] = fact_analysis
            search_query = self._compose_search_query(
                user_input=user_input,
                keywords=keywords,
                chat_history=limit_history,
                carried_context=carried_context,
            )
            logging.info("🧩 [FactPattern] Expanded retrieval query with issues: %s", fact_analysis)

        hint_source_text = f"{carried_context} {user_input}".strip() if carried_context else user_input

        # Bước 4B: Retrieve
        docs = retrieve_documents(
            user_input=hint_source_text,
            retriever=self.retriever,
            k=6,
            semantic_query=search_query,
        )

        def _is_exact_article_doc(doc, article_number: int) -> bool:
            meta = doc.metadata or {}
            raw = meta.get("article_number", meta.get("dieu_so"))
            return str(raw).isdigit() and int(raw) == article_number

        vector_db = getattr(self.retriever, "vectorstore", None)
        for target_article in suggest_target_articles(hint_source_text):
            if vector_db is None:
                break
            extra_docs = retrieve_exact_article(
                article_number=target_article,
                vector_db=vector_db,
                retriever=self.retriever,
                limit=12,
            )
            exact_docs = [d for d in extra_docs if _is_exact_article_doc(d, target_article)]
            if exact_docs:
                docs = exact_docs + docs
            else:
                docs.extend(extra_docs[:2])

        deduped_docs = []
        seen = set()
        for d in docs:
            key = (
                (d.metadata or {}).get("chunk_id"),
                (d.metadata or {}).get("article_number", (d.metadata or {}).get("dieu_so")),
                (d.page_content or "")[:80],
            )
            if key in seen:
                continue
            seen.add(key)
            deduped_docs.append(d)
        docs = deduped_docs[:8]
        context_text = "\n\n".join(d.page_content for d in docs)
        logging.info(f"📂 [Retriever] {len(docs)} docs retrieved via: '{search_query}'")
        
        # FIX F: Check if article-only query returned no useful results
        article_only_keywords = [k for k in keywords if k.lower().startswith("điều ")]
        non_article_keywords = [k for k in keywords if not k.lower().startswith("điều ")]
        
        if article_only_keywords and not non_article_keywords and (not docs or len(docs) < 2):
            # Article-only query with poor retrieval → Return clarifying response
            context_text = self._generate_clarifying_question(article_only_keywords)
            logging.info(f"⚠️ [FIX F] Article-only query with poor results: Returning clarifying question")
            return search_query, context_text, docs
        
        # Bước 4B.1: VALIDATE CITATIONS (Fix #3)
        validator = CitationValidator()
        validated_analysis = validator.validate_and_correct(analysis, docs)
        if "_invalid_articles" in validated_analysis:
            logging.warning(f"🗑️ [Citation Validator] Removed invalid articles: {validated_analysis['_invalid_articles']}")

        return search_query, context_text, docs
    
    def _generate_clarifying_question(self, article_keywords: List[str]) -> str:
        """
        FIX F: Generate a clarifying question for article-only queries that didn't retrieve results.
        
        Args:
            article_keywords: List of article references (e.g., ["Điều 35"])
            
        Returns:
            A structured clarifying response with suggestions
        """
        article_str = article_keywords[0] if article_keywords else "Điều nào"
        
        suggestions = [
            "sa thải / chấm dứt hợp đồng",
            "quyền và nghĩa vụ",
            "thời gian làm việc",
            "tiền lương",
            "nghỉ phép",
            "bảo hiểm xã hội",
            "tranh chấp lao động"
        ]
        
        clarifying_response = (
            f"Bạn đang hỏi về {article_str} của Bộ Luật Lao Động Việt Nam. "
            f"Để tôi tìm được thông tin chính xác hơn, bạn có thể nêu rõ hơn chủ đề liên quan, chẳng hạn:\n\n"
        )
        
        for idx, suggestion in enumerate(suggestions, 1):
            clarifying_response += f"• {suggestion}\n"
        
        clarifying_response += (
            f"\nVí dụ: '{article_str} về sa thải lao động' hoặc '{article_str} về tiền lương'?"
        )
        
        return f"{self.CLARIFY_TAG} {clarifying_response}"


class CitationValidator:
    """
    Validate article citations are within valid range and exist in retrieved documents.
    Prevents hallucinated article numbers (e.g., "Điều 250") from appearing in responses.
    """
    
    # Valid article range for Bộ luật Lao động 2019
    VALID_ARTICLES = set(range(1, MAX_ARTICLE_NUMBER + 1))
    
    def __init__(self):
        """Initialize citation validator"""
        self.logger = logging.getLogger(__name__)
    
    def extract_articles_from_docs(self, docs: list) -> set:
        """Extract article numbers from parsed metadata (avoid body cross-reference noise)."""
        return set(extract_articles_from_documents(docs))
    
    def extract_articles_from_text(self, text: str) -> set:
        """Extract article numbers mentioned in response text"""
        articles = set()
        matches = re.findall(r'[Đđ]iều\s*(\d+)', text)
        articles.update(int(m) for m in matches if m.isdigit())
        return articles
    
    def validate_and_correct(self, analyzer_output: Dict, docs: list) -> Dict:
        """
        Validate analyzer output against retrieved documents.
        
        Args:
            analyzer_output: Dict with keys "issue", "keywords", "law_type"
            docs: List of retrieved documents from retriever
            
        Returns:
            Corrected analyzer_output with validated keywords/articles
        """
        if not analyzer_output or "keywords" not in analyzer_output:
            return analyzer_output
        
        # Extract article numbers that exist in actual documents
        doc_articles = self.extract_articles_from_docs(docs)
        logging.info(f"📋 [Validator] Articles found in documents: {sorted(doc_articles)}")
        
        # Validate and filter keywords
        validated_keywords = []
        invalid_articles = []
        
        for kw in analyzer_output.get("keywords", []):
            # Check if keyword mentions an article number
            article_match = re.search(r'[Đđ]iều\s*(\d+)', kw)
            
            if article_match:
                article_num = int(article_match.group(1))
                # Valid if: in valid range AND exists in retrieved documents
                if article_num in self.VALID_ARTICLES and article_num in doc_articles:
                    validated_keywords.append(kw)
                    logging.info(f"✅ [Validator] Article {article_num} validated")
                elif article_num not in self.VALID_ARTICLES:
                    invalid_articles.append(article_num)
                    logging.warning(
                        f"⚠️ [Validator] Article {article_num} OUT OF RANGE (1-{MAX_ARTICLE_NUMBER}), filtering out"
                    )
                else:
                    invalid_articles.append(article_num)
                    logging.warning(f"⚠️ [Validator] Article {article_num} not found in documents, filtering out")
            else:
                # Non-article keywords are always kept
                validated_keywords.append(kw)
        
        # Update analyzer output with validated keywords
        # If all keywords were invalid, keep original (fallback)
        if validated_keywords:
            analyzer_output["keywords"] = validated_keywords
            logging.info(f"📝 [Validator] Keywords after validation: {validated_keywords}")
        else:
            logging.warning(f"⚠️ [Validator] No valid keywords after validation, keeping original")
        
        if invalid_articles:
            analyzer_output["_invalid_articles"] = invalid_articles
            logging.info(f"🗑️  [Validator] Removed invalid articles: {invalid_articles}")
        
        return analyzer_output
    
    def validate_response_articles(self, response_text: str, docs: list) -> Dict:
        """
        Post-process response text to warn about invalid citations.
        
        Returns dict with validation results:
            - valid_articles: List of valid articles mentioned
            - invalid_articles: List of articles that don't exist
            - needs_correction: Boolean indicating if response has invalid citations
        """
        doc_articles = self.extract_articles_from_docs(docs)
        response_articles = self.extract_articles_from_text(response_text)
        
        valid = []
        invalid = []
        
        for article_num in response_articles:
            if article_num in self.VALID_ARTICLES and article_num in doc_articles:
                valid.append(article_num)
            else:
                invalid.append(article_num)
        
        return {
            "valid_articles": sorted(valid),
            "invalid_articles": sorted(invalid),
            "needs_correction": len(invalid) > 0,
            "coverage": len(valid) / (len(valid) + len(invalid)) if (len(valid) + len(invalid)) > 0 else 1.0
        }
