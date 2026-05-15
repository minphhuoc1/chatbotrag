# Bot Flow Graph (Latest)

```mermaid
flowchart TD
    A["App start"] --> B["Load .env + config"]
    B --> C["Load embeddings + Chroma DB"]
    C --> D["Create LLM clients via llm_factory<br/>provider=groq|ollama<br/>reasoner/analyzer models"]
    D --> E["Provider health check"]
    E --> F{"Startup ok?"}
    F -- "No" --> F1["Show startup error + stop"]
    F -- "Yes" --> G["Render Streamlit UI + wait user input"]

    G --> H["Intent classification<br/>(rule first, then LLM fallback if needed)"]
    H --> I{"Intent == LEGAL?"}
    I -- "No" --> I1["Return GREETING/OFF_TOPIC response"]
    I1 --> Z["Persist chat history + log"]

    I -- "Yes" --> J["Analyzer chain -> legal keywords<br/>(fallback extractor on parse failure)"]
    J --> K["Retrieve documents<br/>semantic + exact-article enrichment"]
    K --> L["Build retrieval evidence rows"]
    L --> M["Resolve article ambiguity<br/>(ask-back when needed)"]
    M --> N{"Need clarify now?"}
    N -- "Yes" --> N1["Return clarify/fallback"]
    N1 --> Z

    N -- "No" --> O["Assess retrieval strength"]
    O --> P{"Strong enough?"}
    P -- "No" --> P1["Insufficient-context response"]
    P1 --> Z

    P -- "Yes" --> Q{"Query mode"}
    Q -- "quote_request + exact article" --> Q1["Return exact article text"]
    Q1 --> Q2["Quote grounding validation"]
    Q2 --> Q3{"Valid?"}
    Q3 -- "No" --> Q4["Validation fallback"]
    Q3 -- "Yes" --> Z
    Q4 --> Z

    Q -- "article_lookup + exact article" --> R["Return formatted article answer"]
    R --> Z

    Q -- "fact/open-ended" --> S["Reasoner chain generate draft answer"]
    S --> T["Enforce citation contract"]
    T --> U["Validate answer vs retrieved context"]
    U --> V{"Validation ok?"}
    V -- "Yes" --> Z
    V -- "No" --> W["Repair citations"]
    W --> X["Re-validate"]
    X --> Y{"Repair ok?"}
    Y -- "Yes" --> Z
    Y -- "No" --> Y1["Validation fallback"]
    Y1 --> Z

    Z --> Z1["Render answer + evidence table + source expander"]
    Z1 --> Z2["Write logs: query/retrieval/validation/answer"]

    %% External runtime behavior
    S -. "Groq SDK may auto-retry on 429" .-> S
```

## Notes
- LLM runtime is provider-based (`groq` or `ollama`) via `src/legal_chatbot/llm_factory.py`.
- Current default setup uses Groq with:
  - reasoner: `openai/gpt-oss-20b`
  - analyzer: `openai/gpt-oss-20b`
- Retrieval/grounding policy remains the main quality gate even with stronger models.

