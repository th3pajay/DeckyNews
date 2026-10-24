from pathlib import Path


def binary_kind(path: Path) -> str:
    return "llamafile" if "llamafile" in path.name else "llama-cli"


LLM_GLOBAL = {
    "n_threads": 2,
    "n_gpu_layers": 0,
    "max_prompt_chars": 2500,
    "temperature": 0.0,
    "repeat_penalty": 1.15,
}

MODEL_CATALOG = {
    "qwen2.5-0.5b": {
        "display_name": "Qwen2.5-0.5B",
        "description": "Default. Instruction-tuned, reliable summaries.",
        "repo": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "filename": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "size_mb": 352,
        "prompt_format": "chatml",
        "n_ctx": 1024,
        "max_gen_tokens": 150,
        "timeout_seconds": 15,
    },
    "qwen3-0.6b": {
        "display_name": "Qwen3-0.6B",
        "description": "Newer Qwen generation, thinking disabled. Better than Qwen2.5-0.5B at following instructions.",
        "repo": "unsloth/Qwen3-0.6B-GGUF",
        "filename": "Qwen3-0.6B-Q4_K_M.gguf",
        "size_mb": 397,
        "prompt_format": "chatml_nothink",
        "n_ctx": 2048,
        "max_gen_tokens": 150,
        "timeout_seconds": 20,
    },
    "gemma3-270m": {
        "display_name": "Gemma 3 270M",
        "description": "Google's tiny instruct model. Very fast, lighter quality.",
        "repo": "unsloth/gemma-3-270m-it-GGUF",
        "filename": "gemma-3-270m-it-Q4_K_M.gguf",
        "size_mb": 253,
        "prompt_format": "gemma",
        "n_ctx": 2048,
        "max_gen_tokens": 150,
        "timeout_seconds": 10,
    },
    "smollm2-360m": {
        "display_name": "SmolLM2-360M",
        "description": "HuggingFace's smallest instruct model. Fastest, lowest quality.",
        "repo": "unsloth/SmolLM2-360M-Instruct-GGUF",
        "filename": "SmolLM2-360M-Instruct-Q4_K_M.gguf",
        "size_mb": 220,
        "prompt_format": "chatml",
        "n_ctx": 2048,
        "max_gen_tokens": 150,
        "timeout_seconds": 10,
    },
}
