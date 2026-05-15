import os
from pathlib import Path

try:
    from langchain_huggingface import HuggingFaceEmbeddings
except ImportError:
    from langchain_community.embeddings import HuggingFaceEmbeddings


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _safe_torch_cuda_available(torch_module) -> bool:
    try:
        return bool(torch_module.cuda.is_available())
    except Exception:
        return False


def _safe_torch_mps_available(torch_module) -> bool:
    try:
        return bool(
            hasattr(torch_module, "backends")
            and hasattr(torch_module.backends, "mps")
            and torch_module.backends.mps.is_available()
        )
    except Exception:
        return False


def _looks_like_blocked_local_proxy(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return False
    return (
        "127.0.0.1:9" in normalized
        or "localhost:9" in normalized
        or "0.0.0.0:9" in normalized
    )


def _has_blocked_proxy_env() -> bool:
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        if _looks_like_blocked_local_proxy(os.getenv(key, "")):
            return True
    return False


def _candidate_hf_cache_roots() -> list[Path]:
    roots = []
    explicit = os.getenv("HF_HUB_CACHE", "").strip()
    if explicit:
        roots.append(Path(explicit).expanduser())

    user_profile = os.getenv("USERPROFILE", "").strip()
    if user_profile:
        roots.append(Path(user_profile) / ".cache" / "huggingface" / "hub")
    return roots


def _find_cached_snapshot(model_name: str) -> str:
    if "/" not in model_name:
        return ""

    cache_key = f"models--{model_name.replace('/', '--')}"
    for root in _candidate_hf_cache_roots():
        snapshot_root = root / cache_key / "snapshots"
        if not snapshot_root.exists():
            continue
        snapshots = [p for p in snapshot_root.iterdir() if p.is_dir()]
        if not snapshots:
            continue
        snapshots.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for snap in snapshots:
            if (snap / "modules.json").exists():
                return str(snap)
    return ""


def _resolve_model_name(default_model: str, local_only: bool) -> str:
    custom_path = os.getenv("EMBED_MODEL_PATH", "").strip()
    if not custom_path:
        if local_only:
            cached = _find_cached_snapshot(default_model)
            if cached:
                return cached
        return default_model

    resolved = Path(custom_path).expanduser()
    if not resolved.exists():
        raise FileNotFoundError(
            f"EMBED_MODEL_PATH không tồn tại: {resolved}"
        )
    return str(resolved)


def _should_use_local_files_only() -> bool:
    explicit = os.getenv("HF_LOCAL_FILES_ONLY", "").strip()
    if explicit:
        return _is_truthy(explicit)

    if _is_truthy(os.getenv("HF_HUB_OFFLINE", "").strip()):
        return True

    # Một số môi trường cấu hình proxy localhost:9 để chặn outbound.
    # Trong trường hợp đó phải ép local-only để tránh retry mạng vô ích.
    if _has_blocked_proxy_env():
        return True

    return (
        os.getenv("QA_NONINTERACTIVE", "").strip() == "1"
        or os.getenv("CI", "").strip().lower() == "true"
    )


def _resolve_embed_device() -> str:
    explicit = (
        os.getenv("LEGAL_CHATBOT_EMBED_DEVICE", "").strip()
        or os.getenv("EMBED_DEVICE", "").strip()
    )
    try:
        import torch  # pylint: disable=import-outside-toplevel
    except Exception:
        torch = None

    if explicit and explicit.lower() != "auto":
        explicit = explicit.lower()
        if explicit == "cuda":
            if torch is not None and _safe_torch_cuda_available(torch):
                return "cuda"
            print("[WARN] EMBED_DEVICE='cuda' nhưng torch không hỗ trợ CUDA. Fallback -> cpu.")
            return "cpu"
        if explicit == "mps":
            if torch is not None and _safe_torch_mps_available(torch):
                return "mps"
            print("[WARN] EMBED_DEVICE='mps' nhưng MPS không khả dụng. Fallback -> cpu.")
            return "cpu"
        if explicit == "cpu":
            return "cpu"
        print(f"[WARN] EMBED_DEVICE='{explicit}' không hợp lệ. Fallback -> cpu.")
        return "cpu"

    try:
        if torch is not None and _safe_torch_cuda_available(torch):
            return "cuda"
        if torch is not None and _safe_torch_mps_available(torch):
            return "mps"
    except Exception:
        pass
    return "cpu"


def get_embedding_runtime_device(embeddings) -> str:
    client = getattr(embeddings, "_client", None) or getattr(embeddings, "client", None)
    device = getattr(client, "device", None)
    return str(device) if device else "unknown"


def create_embeddings(default_model: str):
    local_only = _should_use_local_files_only()
    model_name = _resolve_model_name(default_model, local_only)
    embed_device = _resolve_embed_device()

    kwargs = {"model_name": model_name}
    cache_folder = os.getenv("HF_CACHE_DIR", "").strip()
    if cache_folder:
        kwargs["cache_folder"] = cache_folder

    model_kwargs = {"device": embed_device}
    if local_only:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        model_kwargs["local_files_only"] = True

    kwargs["model_kwargs"] = model_kwargs

    return HuggingFaceEmbeddings(**kwargs)
