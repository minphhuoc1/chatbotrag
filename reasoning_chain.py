import logging
import re
import json
from typing import Dict, List
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser

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

    def __init__(self, retriever, llm_extract, llm_reason, system_prompt):
        """
        Khởi tạo Engine với các tài nguyên truyền vào từ app.py
        - retriever: Đối tượng kéo dữ liệu từ ChromaDB
        - llm_extract: Model dùng để phân tách JSON từ khóa (Nên dùng model chạy format="json")
        - llm_reason: Model chính gánh vác State Machine Prompt (Qwen 3B/7B)
        - system_prompt: Đọc từ file hệ thống system_prompt.md
        """
        self.retriever = retriever
        self.llm_extract = llm_extract
        self.llm_reason = llm_reason
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
             "\n=== MẤU VÍ DỤ ĐÚNG ===\n"
             "INPUT: 'Sa thải lao động nữ mang thai, tôi biết gì về quyền của tôi?'\n"
             "OUTPUT: {\"issue\": \"Sa thải lao động nữ mang thai\", \"keywords\": [\"sa thải\", \"mang thai\", \"bảo vệ lao động nữ\"], \"law_type\": \"luật lao động\"}\n"
             "\n"
             "INPUT: 'Làm việc 50 tiếng/tuần, lương tối thiểu vùng là bao nhiêu?'\n"
             "OUTPUT: {\"issue\": \"Yêu cầu về giờ làm việc và lương tối thiểu\", \"keywords\": [\"giờ làm việc\", \"lương tối thiểu\", \"vùng\"], \"law_type\": \"luật lao động\"}\n"
             "\n"
             "INPUT: 'Không được nghỉ phép hằng năm 12 ngày, sao thế?'\n"
             "OUTPUT: {\"issue\": \"Từ chối nghỉ phép hằng năm\", \"keywords\": [\"nghỉ phép\", \"thâm niên\", \"quyền lợi\"], \"law_type\": \"luật lao động\"}\n"
              "\n"
              "INPUT: 'Người lao động được nghỉ phép bao nhiêu ngày một năm?'\n"
              "OUTPUT: {\"issue\": \"Quyền nghỉ phép hằng năm\", \"keywords\": [\"nghỉ phép\", \"hằng năm\"], \"law_type\": \"luật lao động\"}\n"
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
        self.analyzer_chain = self.analyzer_prompt | self.llm_extract | JsonOutputParser()

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
        keywords = [f"Điều {m}" for m in article_matches if 1 <= int(m) <= 182]
        
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

    def _remove_chinese_characters(self, text: str) -> str:
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
        return cleaned.strip()

    def run(self, user_input: str, chat_history: list = None) -> tuple:
        """
        Thực thi toàn bộ luồng RAG (blocking). Dùng cho QA test.
        Returns: (final_answer: str, context_text: str)
        """
        if chat_history is None:
            chat_history = []

        search_query, context_text = self._analyze_and_retrieve(user_input, chat_history)

        final_answer = self.reasoner_chain.invoke({
            "context": context_text,
            "chat_history": chat_history[-6:],
            "input": user_input
        })
        
        # Filter out Chinese characters if present
        final_answer = self._remove_chinese_characters(final_answer)

        return final_answer, context_text


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
        search_query, context_text = self._analyze_and_retrieve(user_input, chat_history)
        yield ("context", context_text)

        # Pha 2: Reasoner stream (từng token)
        full_response = ""
        for chunk in self.reasoner_chain.stream({
            "context": context_text,
            "chat_history": chat_history[-6:],
            "input": user_input
        }):
            # Accumulate response
            full_response += chunk
            # Filter CJK characters from chunk if needed
            filtered_chunk = self._remove_chinese_characters(chunk)
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
        """
        limit_history = chat_history[-4:] if len(chat_history) >= 4 else chat_history

        # Bước 4A: Trích xuất keyword từ JSON (với fallback)
        keywords = []
        search_query = ""
        analysis = {}
        
        try:
            # Try JSON parsing first
            analysis = self.analyzer_chain.invoke({
                "input": user_input,
                "chat_history": limit_history
            })
            keywords = analysis.get("keywords", [])
            search_query = " ".join(keywords)
            logging.info(f"✅ [Analyzer] JSON success: {analysis}")
            logging.info(f"🔍 [Analyzer] Keywords extracted: {keywords}")
            
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
            keywords = self._extract_keywords_fallback(user_input)
            search_query = " ".join(keywords)
            logging.info(f"✅ [Analyzer] Fallback keywords: {keywords}")
            analysis = {"keywords": keywords, "issue": user_input[:100], "law_type": "luật lao động"}
            
        except Exception as e:
            # Broader exception handling
            logging.error(f"❌ [Analyzer] Unexpected error: {e}")
            logging.info(f"📌 [Analyzer] Switching to fallback keyword extraction...")
            keywords = self._extract_keywords_fallback(user_input)
            search_query = " ".join(keywords)
            logging.info(f"✅ [Analyzer] Fallback keywords: {keywords}")
            analysis = {"keywords": keywords, "issue": user_input[:100], "law_type": "luật lao động"}

        # Bước 4B: Retrieve
        docs = self.retriever.invoke(search_query)
        context_text = "\n\n".join(d.page_content for d in docs)
        logging.info(f"📂 [Retriever] {len(docs)} docs retrieved via: '{search_query}'")
        
        # Bước 4B.1: VALIDATE CITATIONS (Fix #3)
        validator = CitationValidator()
        validated_analysis = validator.validate_and_correct(analysis, docs)
        if "_invalid_articles" in validated_analysis:
            logging.warning(f"🗑️ [Citation Validator] Removed invalid articles: {validated_analysis['_invalid_articles']}")

        return search_query, context_text


class CitationValidator:
    """
    Validate article citations are within valid range and exist in retrieved documents.
    Prevents hallucinated article numbers (e.g., "Điều 250") from appearing in responses.
    """
    
    # Valid article range for Vietnam Labor Law 2019 (Bộ Luật Lao Động 2019)
    VALID_ARTICLES = set(range(1, 183))  # Articles 1-182
    
    def __init__(self):
        """Initialize citation validator"""
        self.logger = logging.getLogger(__name__)
    
    def extract_articles_from_docs(self, docs: list) -> set:
        """Extract all article numbers present in documents"""
        articles = set()
        for doc in docs:
            # Pattern: "Điều 35", "Điều 113", etc.
            matches = re.findall(r'Điều\s*(\d+)', doc.page_content)
            articles.update(int(m) for m in matches if m.isdigit())
        return articles
    
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
                    logging.warning(f"⚠️ [Validator] Article {article_num} OUT OF RANGE (1-182), filtering out")
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
