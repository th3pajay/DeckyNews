# Architecture

DeckyNews is a Decky Loader plugin: a React frontend in the Quick Access Menu and a Python backend that fetches feeds, stores articles, and optionally summarizes them with a local model.

## Layout

```
main.py                  Decky entry point: Plugin (RPC surface), NewsFetcher, SummarizationManager
bundle.py                Builds DeckyNews.zip (frontend, backend, Linux x86_64 Python deps)
plugin.json              Decky manifest
src/
  admission.py           Should a summary run now? Circuit breaker, rate limiter, resource monitor, run plan
  summarizer.py          One summarization run: admit, load, extract, prompt, infer, validate
  model_runtime.py       Model and binary lifecycle: download, load, infer, idle unload
  article_text.py        Article text extraction with fallbacks and a blocked-host memory
  prompt_builder.py      Prompt formats, output cleaning and validation
  llama_inference.py     Subprocess wrapper around llamafile / llama-cli
  models.py              MODEL_CATALOG, LLM_GLOBAL, binary_kind()
  hardware.py            CPU temperature, memory, game detection
  settings.py            DEFAULT_SETTINGS and SettingsManager
  database.py            SQLite article store (schema v3, WAL)
  sqlite_writer.py       Shared serialized write queue used by both databases
  deduplicator.py        Title-bucket + edit-distance duplicate detection
  telemetry.py           Per-summary metrics in their own SQLite file
  migrations.py          One-time cleanups
  index.tsx, components/, hooks/, feedLogic.ts, api.ts, types.ts, utils.ts    Frontend
tests/                   pytest suite
```

## Fetching news

`NewsFetcher` pulls each enabled source on a timer (configurable, default 30 min). Failing sources back off independently. New articles go through the deduplicator and into SQLite in batches. The frontend reads pages through the Plugin RPC methods.

## Summarizing an article

`Summarizer.run` is the whole pipeline. Its collaborators are injected, so it is testable without a model.

1. `Admission.check` refuses the run when the circuit breaker is open, a thermal recovery is in progress, the cooldown is active, RAM is under 800 MB or the CPU is over the ceiling, or a game is running.
2. `ModelRuntime.load_model` makes sure the model file and the llamafile binary exist, downloading them if needed, then starts the runner.
3. `article_text.extract` tries the full page, then the mobile page, then the AMP page, then the feed excerpt. Hosts that return 401 or 403 are remembered as blocked for a week.
4. In parallel, `Admission.plan` picks the token budget and thread count. A hot CPU gets fewer tokens and one thread.
5. `prompt_builder.build_prompt` formats the text for the model (`chatml`, `chatml_nothink`, `llama3`, `gemma` or `completion`).
6. `ModelRuntime.infer` runs the model on a single worker thread under a timeout.
7. `prompt_builder.validate_output` rejects short or apologetic output and trims a dangling last sentence.
8. Success starts the cooldown. Any failure counts against the circuit breaker: three failures open it for five minutes.

The model is unloaded after the idle timeout (default 60 s) unless an inference is in flight.

## llamafile

The release zip bundles `bin/llamafile` (an APE binary). On the Deck, `llama_inference` runs it as `/bin/sh llamafile ...` with `LD_LIBRARY_PATH=/usr/lib:/usr/lib64` and `LD_PRELOAD` cleared. `llama-cli` is supported as a legacy fallback and gets its own directory on `LD_LIBRARY_PATH`. `ModelRuntime.binary_candidates()` is the single source of truth for where binaries are looked up. A missing binary is downloaded at load time.

## Storage

- Articles: `database.py`, SQLite with WAL, thread-local reads, one serialized writer (`sqlite_writer.py`). `is_read` is the read-state source of truth.
- Telemetry: a separate SQLite file using the same writer. Records older than 48 hours are pruned.
- Settings: `settings.json`, written atomically. A corrupt file is renamed to `settings.json.corrupt` and defaults are used.

## Settings

`DEFAULT_SETTINGS` in `src/settings.py` is the schema. Updates are validated for key and type, applied all-or-nothing, and live-applied through `SummarizationManager.apply_setting`. `src/types.ts` mirrors the schema, and a test fails if the two drift apart.

## Packaging

`pnpm run build && python bundle.py` produces `DeckyNews.zip`. Python dependencies are bundled into `py_modules/` as Linux x86_64 wheels for the Python version in `LOADER_PYTHONS`. Zip paths must use forward slashes. The bundle must stay under 20 MB excluding llamafile.

## Tests

`python -m pytest` runs the suite in `tests/`. Fakes stand in for hardware, the clock, the network and the model subprocess, so tests run on any OS.
