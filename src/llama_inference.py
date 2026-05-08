"""LLM inference using llamafile/llama.cpp subprocess."""

import os
import re
import signal
import subprocess
from pathlib import Path
from typing import Optional


class LlamaCppSubprocess:
    """Run llama.cpp via subprocess using llamafile or llama-cli binary."""

    _RE_TPS = re.compile(r'eval time.*?(\d+\.\d+)\s+tokens per second')
    _RE_PROMPT_EVAL = re.compile(r'prompt eval time\s+=\s+(\d+\.\d+)\s+ms')
    _RE_TOTAL_TOKENS = re.compile(r'total time.*?/\s+(\d+)\s+tokens')
    _RE_LOAD = re.compile(r'load time\s+=\s+(\d+\.\d+)\s+ms')

    def __init__(self, binary_path: Optional[str] = None, model_path: Optional[str] = None):
        self.binary_path = binary_path or self._find_binary()
        self.model_path = model_path

        if self.binary_path is None:
            raise FileNotFoundError("Could not find llama.cpp binary")

    def _find_binary(self) -> Optional[str]:
        """Find llamafile or llama-cli binary and ensure it's executable."""
        plugin_dir = Path(__file__).parent.parent

        candidates = [
            plugin_dir / "bin" / "llamafile",
            plugin_dir / "bin" / "llamafile-0.9.3",
            Path.home() / "homebrew" / "plugins" / "DeckyNews" / "bin" / "llamafile",
            plugin_dir / "bin" / "llama-cli",
            plugin_dir / "bin" / "main",
            Path.home() / "homebrew" / "plugins" / "DeckyNews" / "bin" / "llama-cli",
            Path("/usr/local/bin/llama-cli"),
        ]

        for path in candidates:
            if not path.exists():
                continue

            is_executable = os.access(path, os.X_OK)

            if not is_executable:
                try:
                    import stat
                    current_mode = path.stat().st_mode
                    path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

                    if os.access(path, os.X_OK):
                        print(f"[LlamaInference] Fixed permissions for {path}")
                        return str(path)
                except (OSError, PermissionError):
                    continue
            else:
                return str(path)

        return None

    def summarize(self, text: str, max_tokens: int = 150, system_prompt: str = None, n_threads: int = 2, prompt_override: Optional[str] = None, n_ctx: int = 1024, prompt_format: str = "chatml") -> dict:
        """
        Summarize text using llama.cpp.

        Args:
            text: Article text to summarize
            max_tokens: Maximum tokens to generate
            system_prompt: System prompt for ChatML format (ignored when prompt_override is set)
            n_threads: Number of CPU threads to use
            prompt_override: If provided, use this raw prompt instead of building ChatML format
            n_ctx: Context size in tokens (model-specific)

        Returns:
            dict with keys:
                - summary: str (the generated summary text)
                - tps: float (tokens per second during eval)
                - ttft: float (time to first token in ms)
                - prompt_eval_time: float (prompt processing time in ms)
                - total_tokens: int (total tokens generated)
                - stop_reason: str ('stop', 'length', 'error')
        """
        if self.model_path is None:
            raise ValueError("Model path not set")

        if prompt_override is not None:
            prompt = prompt_override
        else:
            if system_prompt is None:
                system_prompt = "You are a gaming news summarizer. Summarize in 2-3 sentences."

            if prompt_format == "llama3":
                prompt = f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n{system_prompt}<|eot_id|><|start_header_id|>user<|end_header_id|>\nSummarize this article:\n\n{text}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n"
            elif prompt_format == "chatml_nothink":
                prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\nSummarize this article:\n\n{text}\n/no_think<|im_end|>\n<|im_start|>assistant\n"
            else:
                prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\nSummarize this article:\n\n{text}<|im_end|>\n<|im_start|>assistant\n"

        cmd = [
            self.binary_path,
            "-m", self.model_path,
            "-p", prompt,
            "-n", str(max_tokens),
            "--temp", "0.2",
            "--min-p", "0.05",
            "-ngl", "0",
            "-t", str(n_threads),
            "-c", str(n_ctx),
            "--repeat-penalty", "1.3",
            "--repeat-last-n", str(max_tokens),
            "--no-display-prompt",
        ]

        env = os.environ.copy()
        bin_dir = str(Path(self.binary_path).parent)
        is_llamafile = "llamafile" in Path(self.binary_path).name

        if is_llamafile:
            cmd = ["/bin/sh", self.binary_path] + cmd[1:]
            print(f"[LlamaInference] Using /bin/sh wrapper for llamafile APE binary")
            env["LD_LIBRARY_PATH"] = "/usr/lib:/usr/lib64"
            env.pop("LD_PRELOAD", None)
            print(f"[LlamaInference] Using sanitized System-First environment for llamafile")
        else:
            env["LD_LIBRARY_PATH"] = f"{bin_dir}:{env.get('LD_LIBRARY_PATH', '')}"

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
            errors='replace',
            start_new_session=True,
            env=env
        )
        try:
            stdout, stderr = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.communicate()
            raise TimeoutError("Summarization timed out")

        if proc.returncode == 0:
            output = stdout.strip()
            for sep in ("<|im_end|>", "<|eot_id|>"):
                if sep in output:
                    output = output.split(sep)[0]
            output = output.strip()

            output = re.sub(r'<think>(?:.*?</think>|.*)', '', output, flags=re.DOTALL).strip()

            for prefix in ("Here is the summary of the article:", "Here is a summary of the article:", "Here is a summary:", "Summary:"):
                if output.lower().startswith(prefix.lower()):
                    output = output[len(prefix):].strip()
                    break

            metrics = self._parse_timing_metrics(stderr)
            metrics['summary'] = output
            metrics['stop_reason'] = 'stop' if ('<|im_end|>' in stdout or '<|eot_id|>' in stdout or prompt_override is not None) else 'length'

            return metrics
        else:
            raise RuntimeError(f"llama.cpp failed: {stderr}")

    def _parse_timing_metrics(self, stderr: str) -> dict:
        metrics = {
            'tps': None,
            'ttft': None,
            'prompt_eval_time': None,
            'total_tokens': None,
            'load_duration': None,
        }

        m = self._RE_TPS.search(stderr)
        if m:
            metrics['tps'] = float(m.group(1))

        m = self._RE_PROMPT_EVAL.search(stderr)
        if m:
            metrics['prompt_eval_time'] = float(m.group(1))
            metrics['ttft'] = float(m.group(1))

        m = self._RE_TOTAL_TOKENS.search(stderr)
        if m:
            metrics['total_tokens'] = int(m.group(1))

        m = self._RE_LOAD.search(stderr)
        if m:
            metrics['load_duration'] = float(m.group(1)) / 1000.0

        return metrics
