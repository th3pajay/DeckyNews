import re
from typing import Optional, Tuple

_DEFAULT_SYSTEM_PROMPT = "You are a gaming news summarizer. Summarize in 2-3 sentences."
_STOP_SEPARATORS = ("<|im_end|>", "<|eot_id|>", "<end_of_turn>")
_LEAD_INS = (
    "Here is the summary of the article:",
    "Here is a summary of the article:",
    "Here is a summary:",
    "Summary:",
)
_HALLUCINATION_MARKERS = (
    "I don't have access",
    "I cannot access",
    "I'm unable to",
    "As an AI language model",
    "As an AI assistant",
    "As an AI, I",
    "I apologize",
    "I'm sorry",
)
_THINK_RE = re.compile(r"<think>(?:.*?</think>|.*)", re.DOTALL)


def build_prompt(
    article_text: str,
    prompt_format: str = "chatml",
    system_prompt: Optional[str] = None,
    completion_chars: int = 1000,
) -> str:
    system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT

    if prompt_format == "completion":
        return f"Article: {article_text[:completion_chars]}\n\nTL;DR:"

    if prompt_format == "llama3":
        return (
            f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n{system_prompt}"
            f"<|eot_id|><|start_header_id|>user<|end_header_id|>\nSummarize this article:\n\n{article_text}"
            f"<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n"
        )

    if prompt_format == "gemma":
        return (
            f"<start_of_turn>user\n{system_prompt}\n\nSummarize this article:\n\n{article_text}"
            f"<end_of_turn>\n<start_of_turn>model\n"
        )

    if prompt_format == "chatml_nothink":
        return (
            f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n"
            f"Summarize this article:\n\n{article_text}\n/no_think<|im_end|>\n<|im_start|>assistant\n"
        )


    return (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n"
        f"Summarize this article:\n\n{article_text}<|im_end|>\n<|im_start|>assistant\n"
    )


def clean_output(raw: str) -> str:
    out = raw.strip()
    for sep in _STOP_SEPARATORS:
        if sep in out:
            out = out.split(sep)[0]
    out = _THINK_RE.sub("", out.strip()).strip()
    for lead in _LEAD_INS:
        if out.lower().startswith(lead.lower()):
            out = out[len(lead):].strip()
            break
    return out


def has_stop_token(stdout: str) -> bool:
    return any(sep in stdout for sep in _STOP_SEPARATORS)


def validate_output(output: str) -> Tuple[bool, str]:
    if not output or len(output.strip()) < 20:
        return False, "Output too short"

    lowered = output.lower()
    for marker in _HALLUCINATION_MARKERS:
        if marker.lower() in lowered:
            return False, f"Hallucination detected: {marker}"

    cleaned = output.strip()
    if cleaned[-1] not in ".!?":
        last_period = cleaned.rfind(".")
        if last_period > len(cleaned) // 2:
            cleaned = cleaned[:last_period + 1]
    return True, cleaned
