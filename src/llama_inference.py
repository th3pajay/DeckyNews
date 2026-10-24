import os
import re
import signal
import subprocess
from pathlib import Path
from typing import Optional

from src import prompt_builder


class LlamaCppSubprocess:

    _RE_TPS = re.compile(r'(?<!prompt )eval time.*?(\d+\.\d+)\s+tokens per second')
    _RE_PROMPT_EVAL = re.compile(r'prompt eval time\s+=\s+(\d+\.\d+)\s+ms')
    _RE_TOTAL_TOKENS = re.compile(r'total time.*?/\s+(\d+)\s+tokens')
    _RE_LOAD = re.compile(r'load time\s+=\s+(\d+\.\d+)\s+ms')

    def __init__(self, binary_path: str, model_path: Optional[str] = None, binary_kind: str = "llamafile"):
        if not binary_path:
            raise FileNotFoundError("llama.cpp binary path not provided")
        self.binary_path = binary_path
        self.model_path = model_path
        self.binary_kind = binary_kind

    def summarize(self, prompt: str, max_tokens: int = 150, n_threads: int = 2, n_ctx: int = 1024) -> dict:
        if self.model_path is None:
            raise ValueError("Model path not set")

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
        is_llamafile = self.binary_kind == "llamafile"

        if is_llamafile:


            cmd = ["/bin/sh", self.binary_path] + cmd[1:]
            env["LD_LIBRARY_PATH"] = "/usr/lib:/usr/lib64"
            env.pop("LD_PRELOAD", None)
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
            metrics = self._parse_timing_metrics(stderr)
            metrics['summary'] = prompt_builder.clean_output(stdout)
            metrics['stop_reason'] = 'stop' if prompt_builder.has_stop_token(stdout) else 'length'
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
