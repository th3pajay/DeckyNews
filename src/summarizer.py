import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Protocol, Tuple

from src import prompt_builder
from src.admission import Admission
from src.article_text import Extraction, ExtractionError


class Backend(Protocol):
    async def load_model(self) -> Tuple[bool, Optional[str]]: ...
    async def extract(self, url: str, timeout_seconds: float, max_chars: int,
                      excerpt: Optional[str] = None) -> Extraction: ...
    async def infer(self, prompt: str, *, max_tokens: int, n_threads: int, n_ctx: int,
                    timeout_seconds: float) -> Dict: ...


@dataclass
class Outcome:
    success: bool = False
    summary: Optional[str] = None
    error: Optional[str] = None
    load_failed: bool = False
    llm_metrics: Optional[Dict] = None
    article_text: Optional[str] = None
    fetch_duration: Optional[float] = None
    status: Optional[Dict] = None
    diagnostics: Optional[Dict] = None
    text_source: Optional[str] = None
    steps: Optional[list] = None

    def to_response(self) -> Dict:
        resp = {"success": self.success, "summary": self.summary, "error": self.error, "status": self.status}
        if self.diagnostics is not None:
            resp["diagnostics"] = self.diagnostics
        if self.llm_metrics is not None:
            resp["llm_metrics"] = self.llm_metrics
        if self.text_source is not None:
            resp["text_source"] = self.text_source
        if self.steps:
            resp["steps"] = self.steps
        return resp


class Summarizer:
    def __init__(
        self,
        backend: Backend,
        admission: Admission,
        *,
        max_prompt_chars: int,
        clock: Callable[[], float] = time.time,
        logger: Optional[logging.Logger] = None,
    ):
        self.backend = backend
        self.admission = admission
        self.max_prompt_chars = max_prompt_chars
        self._clock = clock
        self._log = logger or logging.getLogger("summarizer")

    async def run(self, url: str, *, cfg: Dict[str, Any], system_prompt: str,
                  allow_during_gaming: bool = False, excerpt: Optional[str] = None) -> Outcome:
        blocked = await self.admission.check(allow_during_gaming)
        if blocked:
            return Outcome(error=blocked)

        ok, reason = await self.backend.load_model()
        if not ok:
            return Outcome(error=f"Failed to load LLM: {reason}", load_failed=True)

        try:
            return await self._summarize(url, cfg, system_prompt, excerpt)
        except asyncio.TimeoutError:
            self.admission.record_failure()
            return Outcome(error=f"Inference timed out after {cfg['timeout_seconds']}s")
        except Exception as e:
            self.admission.record_failure()
            self._log.error(f"Summarization error: {e}")
            return Outcome(error=f"Summarization failed: {str(e)}")

    async def _summarize(self, url: str, cfg: Dict[str, Any], system_prompt: str,
                         excerpt: Optional[str]) -> Outcome:
        fetch_start = self._clock()
        try:
            extraction, plan = await asyncio.gather(
                self.backend.extract(url, cfg["timeout_seconds"], self.max_prompt_chars, excerpt),
                self.admission.plan(cfg["max_gen_tokens"]),
            )
        except ExtractionError as e:
            return Outcome(error=f"Failed to extract article content: {e}", steps=e.steps)
        fetch_duration = self._clock() - fetch_start

        text = extraction.text
        if not text:
            return Outcome(error="Failed to extract article content")

        prompt = prompt_builder.build_prompt(text, prompt_format=cfg["prompt_format"], system_prompt=system_prompt)
        raw = await self.backend.infer(
            prompt, max_tokens=plan.max_tokens, n_threads=plan.n_threads, n_ctx=cfg["n_ctx"],
            timeout_seconds=cfg["timeout_seconds"],
        )

        valid, processed = prompt_builder.validate_output(raw.get("summary", ""))
        if not valid:
            self.admission.record_failure()
            return Outcome(error=f"Output validation failed: {processed}",
                           article_text=text, fetch_duration=fetch_duration)

        self.admission.record_success()
        return Outcome(
            success=True,
            summary=processed,
            llm_metrics={
                "tps": raw.get("tps"),
                "ttft": raw.get("ttft"),
                "prompt_eval_time": raw.get("prompt_eval_time"),
                "total_tokens": raw.get("total_tokens"),
                "stop_reason": raw.get("stop_reason", "unknown"),
                "load_duration": raw.get("load_duration"),
            },
            article_text=text,
            fetch_duration=fetch_duration,
            text_source=extraction.method,
            steps=extraction.steps,
        )
