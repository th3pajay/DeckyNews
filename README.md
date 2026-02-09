# DeckyNews
Technical LLM test and integration prototype within the SteamOS / Decky ecosystem

Functionally a new summarization tool, using localized LLM on the SteamOS / Deckky plugin framework, raelizing wide array of telemetry on LLM usage metrics to measure and address valid concerns on resource LLM parasitism, thermal and battery load.

With transparent metrics, local implementation provides the latest scraped gaming news in the Decky / Quick Access Menu under DeckyNews, optionally providing a one-button click to summarize them better and without hype, marketing and within configurable length of TL;DR.

My initial, local aim was to fight 'fire with fire' citing most of the news are quite verbose and algorithmically-optimized in their delivery, so I wanted to compress these articles into a better defined, shorter, locally governed summaries.

The technical stack is quite simple, but beside the functional goal, extends into measurements and trackability how the chosen LLM performs:

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                     Steam Deck UI                       │
│                   (Decky Loader Plugin)                 │
└─────────────────────────────────────────────────────────┘
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
┌───────▼────────┐                  ┌────────▼────────┐
│   Frontend     │                  │    Backend      │
│  React/TypeScript                 │  Python 3.11    │
│  Decky UI      │◄────RPC────────► │  asyncio        │
│  Rollup Build  │                  │  feedparser     │
└────────────────┘                  └─────────┬───────┘
                                              │
                         ┌────────────────────┼─────────────┐
                         │                    │             │
                  ┌──────▼──────┐      ┌─────▼─────┐  ┌────▼────┐
                  │   SQLite    │      │    RSS    │  │  LLM    │
                  │   Database  │      │   Feeds   │  │ Engine  │
                  │   WAL Mode  │      │  (6 src)  │  │Llamafile│
                  └─────────────┘      └───────────┘  └─────────┘
```

The prompts used for summaries:
1. **Analyst** (Default)
   ```
   You are a gaming news summarizer. Summarize the article in 2-3 sentences.
   Focus on: what happened, who is involved, and why it matters to gamers.
   Be factual and concise. Do not add opinions or speculation.
   ```

2. **TL;DR** (Ultra-concise)
   ```
   You are a ultra-concise news summarizer. Summarize the article in ONE sentence.
   Be direct and factual. No fluff, just the core information.
   ```
