import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = os.getenv("LEGAL_CHATBOT_DATA_DIR", str(ROOT_DIR / "data"))
DB_PATH = os.getenv("LEGAL_CHATBOT_DB_PATH", str(ROOT_DIR / "vector_db"))
VECTOR_BACKEND = os.getenv("LEGAL_CHATBOT_VECTOR_BACKEND", "persistent").strip().lower()
LOGS_DIR = os.getenv("LEGAL_CHATBOT_LOGS_DIR", str(ROOT_DIR / "logs"))
PROMPTS_DIR = os.getenv("LEGAL_CHATBOT_PROMPTS_DIR", str(ROOT_DIR / "prompts"))

ANSWER_PROMPT_PATH = os.getenv(
    "LEGAL_CHATBOT_ANSWER_PROMPT_PATH",
    str(ROOT_DIR / "prompts" / "system_prompt_guarded.md"),
)
TEST_CASES_PATH = os.getenv("LEGAL_CHATBOT_TEST_CASES_PATH", str(ROOT_DIR / "test_cases.yaml"))

LLM_PROVIDER = os.getenv("LEGAL_CHATBOT_LLM_PROVIDER", "groq").strip().lower()
LLM_REASONER_MODEL = os.getenv(
    "LEGAL_CHATBOT_REASONER_MODEL",
    os.getenv("LEGAL_CHATBOT_LLM_MODEL", "openai/gpt-oss-20b"),
)
LLM_ANALYZER_MODEL = os.getenv(
    "LEGAL_CHATBOT_ANALYZER_MODEL",
    "llama-3.1-8b-instant",
)
LLM_ANALYZER_FALLBACK_MODEL = os.getenv(
    "LEGAL_CHATBOT_ANALYZER_FALLBACK_MODEL",
    "llama-3.1-8b-instant",
).strip()
LLM_INTENT_MODEL = os.getenv(
    "LEGAL_CHATBOT_INTENT_MODEL",
    "llama-3.1-8b-instant",
).strip()
LLM_INTENT_FALLBACK_MODEL = os.getenv(
    "LEGAL_CHATBOT_INTENT_FALLBACK_MODEL",
    LLM_ANALYZER_FALLBACK_MODEL,
).strip()
LLM_REASONER_FALLBACK_MODEL = os.getenv(
    "LEGAL_CHATBOT_REASONER_FALLBACK_MODEL",
    "llama-3.1-8b-instant",
).strip()
LLM_FAST_MAX_RETRIES = int(os.getenv("LEGAL_CHATBOT_FAST_MAX_RETRIES", "0"))
LLM_REASONER_MAX_RETRIES = int(os.getenv("LEGAL_CHATBOT_REASONER_MAX_RETRIES", "0"))
LLM_TEMPERATURE = float(os.getenv("LEGAL_CHATBOT_LLM_TEMPERATURE", "0.1"))
LLM_TIMEOUT = int(os.getenv("LEGAL_CHATBOT_LLM_TIMEOUT", "60"))
LLM_REASONER_MAX_TOKENS = int(os.getenv("LEGAL_CHATBOT_REASONER_MAX_TOKENS", "768"))
LLM_ANALYZER_MAX_TOKENS = int(os.getenv("LEGAL_CHATBOT_ANALYZER_MAX_TOKENS", "256"))
LLM_INTENT_MAX_TOKENS = int(os.getenv("LEGAL_CHATBOT_INTENT_MAX_TOKENS", "128"))
REASONER_MAX_CONTEXT_CHARS = int(os.getenv("LEGAL_CHATBOT_REASONER_MAX_CONTEXT_CHARS", "6500"))
REASONER_MAX_CONTEXT_DOCS = int(os.getenv("LEGAL_CHATBOT_REASONER_MAX_CONTEXT_DOCS", "6"))

# Backward compatibility with legacy imports.
LLM_MODEL = LLM_REASONER_MODEL

EMBED_MODEL = os.getenv(
    "LEGAL_CHATBOT_EMBED_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
TOP_K = int(os.getenv("LEGAL_CHATBOT_TOP_K", "6"))
MAX_ARTICLE_NUMBER = int(os.getenv("LEGAL_CHATBOT_MAX_ARTICLE_NUMBER", "220"))
PDF_BACKEND = os.getenv("LEGAL_CHATBOT_PDF_BACKEND", "pypdf").strip().lower()
PREPROCESSED_DIR = os.getenv(
    "LEGAL_CHATBOT_PREPROCESSED_DIR",
    str(ROOT_DIR / "data" / "preprocessed"),
)
HINTS_APPROVED_PATH = os.getenv(
    "LEGAL_CHATBOT_HINTS_APPROVED_PATH",
    str(ROOT_DIR / "artifacts" / "hints" / "approved_hints.json"),
)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


# Retrieval routing / hybrid controls (P0)
RETRIEVAL_ENABLE_STRATEGY_ROUTER = _env_flag("LEGAL_CHATBOT_RETRIEVAL_ENABLE_STRATEGY_ROUTER", True)
RETRIEVAL_ENABLE_LEXICAL = _env_flag("LEGAL_CHATBOT_RETRIEVAL_ENABLE_LEXICAL", True)
RETRIEVAL_MAX_QUERY_VARIANTS = int(os.getenv("LEGAL_CHATBOT_RETRIEVAL_MAX_QUERY_VARIANTS", "3"))
RETRIEVAL_RRF_K = int(os.getenv("LEGAL_CHATBOT_RETRIEVAL_RRF_K", "60"))
RETRIEVAL_ENABLE_DETERMINISTIC_ARTICLE_BRANCH = _env_flag(
    "LEGAL_CHATBOT_RETRIEVAL_ENABLE_DETERMINISTIC_ARTICLE_BRANCH",
    True,
)
RETRIEVAL_ENABLE_RERANKER = _env_flag("LEGAL_CHATBOT_RETRIEVAL_ENABLE_RERANKER", True)
RETRIEVAL_ENABLE_METADATA_BOOST = _env_flag("LEGAL_CHATBOT_RETRIEVAL_ENABLE_METADATA_BOOST", True)
RETRIEVAL_RERANK_CANDIDATE_POOL = int(os.getenv("LEGAL_CHATBOT_RETRIEVAL_RERANK_CANDIDATE_POOL", "14"))


# Observability / third-party QA
OBS_LANGFUSE_ENABLED = _env_flag("LEGAL_CHATBOT_LANGFUSE_ENABLED", False)
OBS_PHOENIX_ENABLED = _env_flag("LEGAL_CHATBOT_PHOENIX_ENABLED", False)
OBS_PHOENIX_AUTO_INSTRUMENT = _env_flag("LEGAL_CHATBOT_PHOENIX_AUTO_INSTRUMENT", True)
OBS_PHOENIX_PROJECT = os.getenv("LEGAL_CHATBOT_PHOENIX_PROJECT", "legal-chatbot-rag")
OBS_TRACE_TAG = os.getenv("LEGAL_CHATBOT_TRACE_TAG", "").strip()
