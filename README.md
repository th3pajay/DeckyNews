# DeckyNews

Experimental gaming news aggregator for Steam Deck's Decky Loader with optional on-device AI summarization. Fetches RSS feeds from six sources, deduplicates articles, caches them locally, and runs a quantized LLM entirely on the device — no cloud, no account.

*Respecting Decky Team approach on LLM usage, this solely remains a technical **experiment**. Use at your own risk. You have been **warned**.*


<img height="250" src="\Media\QAM01.png" width="200"/>
<img height="250" src="\Media\QAM02_settings.png" width="200"/>
<img height="250" src="\Media\QAM03_summary_metrics.png" width="200"/>


---

## Table of Contents

1. [Features](#features)
2. [Architecture Overview](#architecture-overview)
3. [Data Flow](#data-flow)
4. [Tech Stack by Layer](#tech-stack-by-layer)
   - [Frontend](#frontend)
   - [Backend](#backend)
   - [LLM Inference](#llm-inference)
   - [Database](#database)
   - [Resource Management](#resource-management)
   - [Telemetry](#telemetry)
   - [Build & Bundle](#build--bundle)
5. [Model Catalog](#model-catalog)
6. [News Sources](#news-sources)
7. [Installation](#installation)
8. [Usage](#usage)
9. [Configuration](#configuration)
10. [Troubleshooting](#troubleshooting)
11. [Development](#development)
12. [License](#license)

---

## Features

- **6 gaming news sources** — IGN, PC Gamer, Steam, Kotaku, GameSpot, Polygon via RSS/Atom
- **7-day offline cache** — SQLite-backed with WAL mode for crash safety
- **Background auto-refresh** — configurable 15–120 minute interval
- **Article deduplication** — Levenshtein edit-distance across 500 most recent articles
- **On-device AI summarization** — Mozilla Llamafile (APE binary), CPU-only, no cloud
- **Multi-model support** — swap quantized GGUF models without rebuilding
- **Resource-aware inference** — guards on CPU temperature, free RAM, gaming vs idle state
- **60 s idle unload** — model evicted from memory after inactivity
- **Full controller support** — D-pad, A/X/L1/R1, pull-to-refresh
- **Three view modes** — Compact, Comfortable, Magazine with glassmorphism effects
- **Sparkline coverage charts** — 24-hour article coverage trends per topic
- **Long-press preview** — bottom-sheet article preview without leaving the list
- **Typewriter summaries** — character-by-character animation with blinking cursor

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Steam Deck Hardware                       │
│                 AMD Zen 2 APU · 16 GB LPDDR5 RAM                │
├───────────────────────┬─────────────────────────────────────────┤
│     SteamOS / KDE     │           Decky Loader Host             │
│                       │      (Python plugin_loader service)      │
├───────────────────────┴──────────────┬──────────────────────────┤
│           Quick Access Menu (QAM)    │                           │
│  ┌───────────────────────────────┐   │   ┌────────────────────┐ │
│  │        Frontend (React)       │◄──┼──►│   Backend (Python) │ │
│  │    src/index.tsx (ESNext)     │   │   │     main.py        │ │
│  │                               │   │   │                    │ │
│  │  ArticleCard  NewsItem        │   │   │  NewsFetcher       │ │
│  │  SkeletonArticle  Sparkline   │   │   │  LLMManager        │ │
│  │  HoverPreviewModal            │   │   │  DatabaseManager   │ │
│  │  TypewriterText               │   │   │  ArticleDedup.     │ │
│  │  Settings Panel               │   │   │  CircuitBreaker    │ │
│  └───────────────────────────────┘   │   └────────┬───────────┘ │
│                                      │            │             │
├──────────────────────────────────────┘            │             │
│                                           ┌───────▼──────────┐  │
│                                           │  LLM Inference   │  │
│                                           │ llama_inference  │  │
│                                           │      .py         │  │
│                                           │                  │  │
│                                           │ LlamaCppSubproc  │  │
│                                           └───────┬──────────┘  │
│                                                   │             │
│                                           ┌───────▼──────────┐  │
│                                           │  llamafile APE   │  │
│                                           │  bin/llamafile   │  │
│                                           │  (static binary) │  │
│                                           └───────┬──────────┘  │
│                                                   │             │
│                                           ┌───────▼──────────┐  │
│                                           │   GGUF Model     │  │
│                                           │ ~/.local/share/  │  │
│                                           │ DeckyPlugins/    │  │
│                                           │ deckynews/       │  │
│                                           │ runtime/models/  │  │
│                                           └──────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### News Fetch Flow

```
30-min timer / user pull-to-refresh
           │
           ▼
    NewsFetcher.refresh_news()
           │
    ┌──────┴──────┐
    │  aiohttp    │  ← async parallel fetch, 15s timeout, 5MB cap
    │  + feedparser│
    └──────┬──────┘
           │  raw RSS articles
           ▼
    CloudScraper fallback?  ──yes──► retry with browser-UA spoof
           │ no
           ▼
    readability-lxml         ← strip nav/ads, extract body text
           │
           ▼
    ArticleDeduplicator      ← Levenshtein O(n²) on 500 newest
           │  unique articles
           ▼
    DatabaseManager.upsert() ← WAL-mode SQLite, schema v2
           │
           ▼
    update_coverage_stats()  ← hourly bucket for sparkline
           │
           ▼
    Frontend notified via IPC → article list re-renders
```

### AI Summarization Flow

```
User taps "Summarize" (X button)
           │
           ▼
    LLMManager._inference()
           │
    resource check ──fail──► return error (temp/RAM/cooldown)
           │ pass
           ▼
    _get_binary_path()       ← auto chmod+x on first run
           │
           ▼
    select model from MODEL_CATALOG
           │
    chatml?──yes──► build <|im_start|>system…<|im_end|> prompt
    completion?──yes► build raw completion prompt
           │
           ▼
    LlamaCppSubprocess.summarize()
           │
    ["/bin/sh", llamafile, "-m", model.gguf,
     "--cli", "-p", prompt,
     "-n", max_tokens, "-t", threads,
     "--ctx-size", n_ctx,
     "--temp", "0.0", "--repeat-penalty", "1.15",
     "--no-display-prompt", "-ngl", "0"]
           │
           ▼
    stdout captured → strip prompt echo → return text
           │
           ▼
    _last_activity_time reset → 60s idle timer restarted
           │
           ▼
    TypewriterText component renders result char-by-char
```

### Background Loop

```
plugin_loader starts main.py
    │
    ├─► DatabaseManager.__init__()   schema migration v1→v2
    ├─► load settings from JSON
    ├─► spawn ThreadPoolExecutor(max_workers=1, nice=19)
    ├─► _start_background_refresh()  asyncio loop, 30-min default
    └─► _start_idle_timeout_monitor() checks _last_activity_time
```

---

## Tech Stack by Layer

### Frontend

| Property | Value |
|---|---|
| Framework | React via `@decky/ui ^4.11.0` |
| Language | TypeScript `^5.6.2`, target ES2020 |
| Module format | ESNext |
| JSX transform | `react-jsx` |
| Bundler | Rollup `^4.53.3` via `@decky/rollup ^1.0.2` |
| Icons | `react-icons ^5.3.0` |
| API bridge | `@decky/api ^1.1.3` (IPC to Python backend) |
| Platform target | Steam Deck Quick Access Menu |
| Strict mode | `noImplicitAny`, `noUnusedLocals`, `noImplicitReturns`, `strict: true` |
| Rendering | Client-side only — no SSR |
| State | `useState` / `useEffect` hooks, no external store |
| Pagination | 10 articles/page, L2/R2 trigger navigation |

**Key components:**

| Component | Purpose |
|---|---|
| `NewsItem` | Single article row with long-press detection |
| `ArticleCard` | 3-mode card (compact / comfortable / magazine) |
| `SkeletonArticle` | Shimmer placeholder during fetch (1.5s CSS loop) |
| `HoverPreviewModal` | Bottom-sheet preview on long-press (≥200ms configurable) |
| `TypewriterText` | Char-by-char AI summary reveal with blinking cursor |
| `SparklineChart` | SVG 24-hour coverage trend (shown at ≥5 duplicates) |
| `DynamicBackdrop` | Blurred image background on article focus |
| `SettingsPanel` | Full settings UI with dropdowns, toggles, sliders |

---

### Backend

| Property | Value |
|---|---|
| Language | Python 3 (Steam Deck system Python 3.10+) |
| Plugin host | Decky Loader `api_version: 1` |
| HTTP client | `aiohttp >=3.9.0`, 15s timeout, 5MB feed cap |
| Feed parsing | `feedparser >=6.0.0` |
| Article extraction | `readability-lxml >=0.8.1` |
| HTML parsing | `lxml >=5.0.0` |
| Cloudflare bypass | `cloudscraper >=1.2.71` (fallback for protected sources) |
| SSL | `certifi >=2023.0.0` |
| System resources | `psutil >=5.9.0` |
| Model download | `huggingface_hub >=0.20.0` |
| Concurrency | `asyncio` + `ThreadPoolExecutor(max_workers=1)` at `nice(19)` |
| Articles per source | 20 max |
| Retry backoff | Exponential, 30s base, max 300s, threshold 3 failures |
| Settings storage | JSON (`~/.local/share/DeckyPlugins/deckynews/settings.json`) |

**Key classes:**

| Class | Responsibility |
|---|---|
| `NewsFetcher` | Async RSS fetch, article extraction, per-source circuit breakers |
| `LLMManager` | Inference orchestration, resource gating, model lifecycle |
| `CircuitBreaker` | Opens after 3 failures, resets after 300s; prevents hammering dead sources |
| `SettingsManager` | JSON-backed settings with typed defaults |

**IPC endpoints (selected):**

| Method | Description |
|---|---|
| `get_news()` | Return paginated articles from DB |
| `refresh_news()` | Trigger immediate RSS fetch + deduplicate |
| `summarize_article(id)` | Run LLM on article body, return summary text |
| `download_model(model_id)` | Stream GGUF from HuggingFace Hub |
| `get_llm_status()` | Return current model state and download progress |
| `set_selected_model(id)` | Swap active model (unloads current) |
| `get_coverage_sparkline(id)` | Return 24-hour hourly coverage buckets |
| `update_setting(key, val)` | Persist a single setting |

---

### LLM Inference

| Property | Value |
|---|---|
| Runtime | Mozilla Llamafile v0.9.3 (APE binary, `/bin/sh` wrapper) |
| Binary format | Actually Portable Executable — contains shell script header |
| Execution wrapper | `["/bin/sh", binary_path, ...]` required for APE on SteamOS |
| Environment | `LD_LIBRARY_PATH=/usr/lib:/usr/lib64`, `LD_PRELOAD` cleared |
| CPU-only | `-ngl 0` (no GPU offload) |
| Temperature | `0.0` (deterministic) |
| Repeat penalty | `1.15` |
| Max prompt chars | 2500 |
| Threading | 2 threads normally, 1 during active game session |
| Adaptive tokens | 150 normal, 80 when CPU > temp ceiling |
| Adaptive threads | 2 idle / 1 gaming (via `get_adaptive_thread_count()`) |
| Idle unload | 60s after last `summarize_article()` call |
| Worker priority | `os.nice(19)` — lowest OS scheduling priority |

**Binary discovery order:**

| Priority | Path |
|---|---|
| 1 | `{plugin_dir}/bin/llamafile` |
| 2 | `{plugin_dir}/bin/llamafile-0.9.3` |
| 3 | `~/homebrew/plugins/DeckyNews/bin/llamafile` |
| 4 | `{plugin_dir}/bin/llama-cli` (legacy fallback) |

**Prompt formats:**

| Format | Models | Structure |
|---|---|---|
| ChatML | `qwen2.5-0.5b` | `<\|im_start\|>system\n{sys}<\|im_end\|>\n<\|im_start\|>user\n{text}<\|im_end\|>\n<\|im_start\|>assistant\n` |
| Completion | `mobilellm-600m` | Raw text prompt with instruction prefix |

---

### Database

| Property | Value |
|---|---|
| Engine | SQLite (schema v2) |
| WAL mode | Yes — crash-safe concurrent reads |
| Synchronous | `NORMAL` |
| Tables | `articles`, `metadata`, `article_coverage` |
| Article retention | 30 days (VACUUM every 7 days) |
| Write pattern | Serial queue via daemon thread (prevents WAL lock contention) |
| Dedup algorithm | `python-Levenshtein ==0.25.0`, O(n²) pairwise edit distance |
| Dedup threshold | 10 edit distance (configurable) |
| Dedup window | 500 most recent articles |
| Coverage tracking | `update_coverage_stats()` — hourly buckets for sparkline |

**Schema (v2):**

```sql
CREATE TABLE articles (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    link        TEXT,
    source      TEXT,
    published   TEXT,
    summary     TEXT,
    body        TEXT,
    ai_summary  TEXT,
    image_url   TEXT,      -- added v2
    favicon_url TEXT,      -- added v2
    fetched_at  TEXT
);

CREATE TABLE metadata (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE article_coverage (    -- added v2
    article_id  TEXT,
    bucket_hour TEXT,
    count       INTEGER DEFAULT 1
);
```

---

### Resource Management

| Property | Value |
|---|---|
| LLM cooldown | 20s between requests (configurable) |
| Circuit breaker | Opens after 3 source failures, resets after 300s |
| RAM floor (normal) | 800 MB free required |
| RAM floor (gaming) | 500 MB free required |
| CPU temp ceiling (normal) | 75°C |
| CPU temp ceiling (gaming) | 75°C (stricter guard via `allowLlmDuringGaming`) |
| Thermal bonus cooldown | +30s after inference when CPU was hot |
| CPU temp source | `/sys/class/hwmon/hwmon*/temp1_input` |
| Fan RPM source | `/sys/class/hwmon/hwmon*/fan1_input` |
| Gaming detection | `psutil` process scan for active game sessions |

**Resource check flow:**

```
summarize_article() called
    │
    ├─ cooldown active?   ──yes──► reject
    ├─ CPU temp > ceiling? ──yes──► reject
    ├─ free RAM < floor?   ──yes──► reject
    ├─ gaming + LLM banned? ─yes──► reject
    └─ all clear ──────────────► proceed
```

---

### Telemetry

| Property | Value |
|---|---|
| Storage | Separate SQLite (`defaults/telemetry.db`) |
| Ring buffer | 48 hours |
| Write queue | `queue.Queue(maxsize=100)` background worker |
| Metrics captured | 25 columns per inference event |
| Fan RPM source | `/sys/class/hwmon/hwmon*/fan1_input` |
| TDP estimate | `10W + (temp − 50) × 0.1`, capped at 15W |
| Energy formula | `(TDP × duration_s) / 3.6` → mWh |
| Flesch readability | `206.835 − 1.015×ASL − 84.6×ASW` |
| AI-probability heuristic | `0.65×TTR_score + 0.35×variance_score` |

**Captured metrics (selected):**

| Metric | Description |
|---|---|
| `model_id` | Model used for this inference session |
| `tps` | Tokens per second |
| `ttft` | Time to first token (ms) |
| `cpu_temp` | °C at inference start |
| `ram_delta_mb` | MB consumed during inference |
| `fan_rpm` | Fan speed at inference |
| `tdp_estimate_w` | Estimated watt draw |
| `energy_mwh` | Milliwatt-hours consumed |
| `flesch_score` | Readability of output |
| `compression_ratio` | Input chars / output chars |
| `ai_probability` | Heuristic for AI-like output |
| `fetch_latency_ms` | RSS fetch round-trip time |
| `ipc_latency_ms` | Frontend→backend call time |

---

### Build & Bundle

| Property | Value |
|---|---|
| Bundle script | `bundle.py` (Python) |
| Frontend build | `pnpm run build` → Rollup → `dist/` |
| Python wheels | Downloaded for `linux_x86_64` / `manylinux_2_17`, `manylinux_2_28`, `manylinux2014` |
| ZIP format | Forward slashes enforced (Windows `Compress-Archive` is broken for Unix extraction) |
| Bundle target | < 20 MB excluding `bin/llamafile` |
| Intel libs removed | 11 patterns: `alderlake`, `cannonlake`, `cascadelake`, `cooperlake`, `haswell`, `icelake`, `ivybridge`, `sandybridge`, `sapphirerapids`, `skylakex`, `sse42` |
| AMD libs kept | `zen4`, `x64`, `piledriver` |
| Binary validation | `bundle.py` aborts if `bin/llamafile` missing |

**Bundle contents:**

```
DeckyNews.zip
├── main.py
├── plugin.json
├── package.json
├── requirements.txt
├── dist/                   ← compiled frontend (Rollup output)
├── src/
│   ├── __init__.py
│   ├── llama_inference.py
│   ├── database.py
│   ├── deduplicator.py
│   └── telemetry.py
├── py_modules/             ← bundled Python deps (linux_x86_64)
├── bin/
│   └── llamafile           ← 294 MB APE binary (NOT in source repo)
├── defaults/
│   ├── defaults.txt
│   └── logos/              ← static source logos for accent extraction
└── assets/
    └── logo.png
```

---

## Model Catalog

| ID | Display Name | Size | Format | Context | Max Tokens | Timeout | Notes |
|---|---|---|---|---|---|---|---|
| `qwen2.5-0.5b` | Qwen2.5-0.5B | 352 MB | ChatML | 1024 | 150 | 15s | Default |
| `mobilellm-600m` | MobileLLM-600M | 430 MB | Completion | 2048 | 120 | 20s | Experimental |
| `llama3.2-1b` | Llama 3.2-1B | 700 MB | Llama3 | 2048 | 150 | 20s | |
| `qwen3-0.6b` | Qwen3-0.6B | 400 MB | ChatML (no-think) | 2048 | 150 | 20s | |

Models are downloaded on first use from HuggingFace Hub to:
`~/.local/share/DeckyPlugins/deckynews/runtime/models/{model_id}/`

---

## News Sources

| Source | Feed URL |
|---|---|
| IGN | `https://feeds.feedburner.com/ign/all` |
| PC Gamer | `https://www.pcgamer.com/rss/` |
| Steam | `https://store.steampowered.com/feeds/news.xml` |
| Kotaku | `https://kotaku.com/rss` |
| GameSpot | `https://www.gamespot.com/feeds/news/` |
| Polygon | `https://www.polygon.com/rss/index.xml` |

Each source has an independent circuit breaker (3 failures → 5-minute pause).

---

## Installation

### Prerequisites

- [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) installed on Steam Deck
- Python 3.10+ (included with Decky Loader)

### From Plugin Store

*Not planned*

### Manual Installation

1. Download `DeckyNews.zip` from [Releases](https://github.com/th3pajay/DeckyNews/releases)
2. In Decky Loader → Developer → Install Plugin from ZIP

### AI Summarization (optional)

Enable **AI Summaries** in Settings. The plugin automatically downloads the llamafile runtime (~294 MB) and the default GGUF model (~350 MB) in one step — no terminal required. Both files are cached locally and never re-downloaded unless deleted.

---

## Usage

### Controls

| Action | Control |
|---|---|
| Scroll articles | D-pad / left analog |
| Open in browser | A button |
| AI summarize | X button |
| Next / prev page | R2 / L2 (triggers) |
| Pull to refresh | Swipe down |
| Long-press preview | Hold article (500ms default) |

### Settings

| Setting | Range | Default | Description |
|---|---|---|---|
| Refresh interval | 15–120 min | 30 min | Background fetch frequency |
| Items per page | 5–20 | 10 | Articles shown per page |
| AI summaries | on/off | off | Enable LLM summarization |
| AI model | dropdown | qwen2.5-0.5b | Active GGUF model |
| AI personality | analyst/journalist/eli5 | analyst | Summary tone |
| View mode | compact/comfortable/magazine | comfortable | Card layout |
| Glass effect | 0–100 | 30 | Glassmorphism blur intensity |
| Source icons | on/off | on | Show favicons on articles |
| Typewriter speed | 10–100 chars/s | 30 | Summary reveal speed |
| Long-press preview | on/off | on | Bottom-sheet article preview |
| Preview delay | 200–1000ms | 500ms | Trigger threshold |
| Performance guard | on/off | on | Block LLM on high temp/low RAM |

---

## Configuration

Settings are stored at:
```
~/.local/share/DeckyPlugins/deckynews/settings.json
```

Runtime models are cached at:
```
~/.local/share/DeckyPlugins/deckynews/runtime/models/
```

SQLite databases:
```
~/.local/share/DeckyPlugins/deckynews/news.db       ← articles
~/.local/share/DeckyPlugins/deckynews/telemetry.db  ← metrics
```

---

## Troubleshooting

### News not loading
```bash
journalctl -u plugin_loader -f | grep -i deckynews
```
Check for circuit breaker events: `CircuitBreaker OPEN for {source}`.

### LLM fails: `Exec format error`

The plugin auto-fixes permissions on startup. If it persists:

```bash
chmod +x ~/homebrew/plugins/DeckyNews/bin/llamafile
# or for the runtime-downloaded location:
chmod +x ~/.local/share/DeckyPlugins/deckynews/runtime/bin/llamafile
```

### LLM fails: `failed to load model`

The GGUF architecture may be unsupported by the bundled llamafile version. Check the model ID in Settings — `qwen2.5-0.5b`, `llama3.2-1b`, and `qwen3-0.6b` are validated against llamafile 0.9.3.

### LLM not running during games

Expected. Set **Allow LLM during gaming** in Settings, or ensure CPU temp is below 75°C and free RAM is above 500 MB.

### Build errors

```bash
rm -rf dist/ node_modules/
pnpm install
pnpm run build
python bundle.py
```

---

## Development

```bash
# Install dependencies
pnpm install
pip install -r requirements.txt

# Build frontend
pnpm run build

# Watch mode (auto-rebuild on save)
pnpm run watch

# Create distribution bundle
python bundle.py
```

### Project structure

```
DeckyProject/
├── main.py                  # Backend: fetch, LLM, DB, settings
├── bundle.py                # Packaging script
├── plugin.json              # Decky Loader manifest
├── src/
│   ├── index.tsx            # React frontend (full plugin UI)
│   ├── types.d.ts           # TypeScript type declarations
│   ├── llama_inference.py   # LLM subprocess wrapper
│   ├── database.py          # SQLite manager (schema v2)
│   ├── deduplicator.py      # Levenshtein deduplication
│   └── telemetry.py         # Inference metrics collector
├── defaults/
│   ├── defaults.txt         # Default settings JSON
│   └── logos/               # Static source logo PNGs
├── assets/
│   └── logo.png             # Plugin icon
└── bin/                     # Binaries (not in repo)
    └── llamafile            # Mozilla Llamafile APE binary
```

### Deployment to Steam Deck

```bash
# Build
pnpm run build && python bundle.py

# Transfer
scp DeckyNews.zip deck@steamdeck:~/

# Install via SSH
ssh deck@steamdeck "curl -L https://... | bash"
# or use Decky Loader → Developer → Install Plugin from ZIP

# Monitor
ssh deck@steamdeck "journalctl -u plugin_loader -f | grep -i deckynews"
```

---

## License

BSD-3-Clause — see [LICENSE](LICENSE)

## Credits

- Built with [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
- LLM inference powered by [Mozilla Llamafile](https://github.com/Mozilla-Ocho/llamafile)
- Default model: [Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF)
- Deduplication: [python-Levenshtein](https://github.com/maxbachmann/Levenshtein)

---

**Privacy:** No external telemetry. All data stays on your device. LLM runs locally — no cloud APIs.

---
## Support
If DeckyNews has saved you some time-to-read, consider supporting the project!

<a href="https://www.buymeacoffee.com/th3pajay"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" width="160" height="45" alt="Buy Me A Coffee"></a>