# DeckyNews

<table>
  <tr>
    <td width="46%" valign="top">
      <img src="media/qam_1.jpg" alt="DeckyNews in the Steam Deck Quick Access Menu" width="100%">
    </td>
    <td valign="top">
      <p><b>Gaming news in your Steam Deck's Quick Access Menu.</b></p>
      <p>Six sources, an offline cache, and optional AI summaries from a small model that runs on the device. No cloud, no account.</p>
      <p><b>Install</b></p>
      <ol>
        <li>Download <code>DeckyNews-vX.Y.Z.zip</code> from <a href="https://github.com/th3pajay/DeckyNews/releases">Releases</a></li>
        <li>In Decky Loader, open Developer and choose Install Plugin from ZIP</li>
      </ol>
    </td>
  </tr>
</table>

> **Experimental.** Respecting the Decky team's approach to LLM usage, DeckyNews is a technical experiment and not a store plugin. AI summaries are off by default, the model runs only on your device, nothing is sent anywhere, and you install it manually. Use at your own risk. You have been warned.

## What it does

<table>
  <tr>
    <td width="33%" valign="top"><b>Reads</b><br>IGN, PC Gamer, Steam, Kotaku, GameSpot and Polygon. Duplicate stories are merged. Everything is cached offline.</td>
    <td width="33%" valign="top"><b>Summarizes</b><br>A small local model on the CPU. It pauses while you game and when the Deck runs hot. When a site blocks readers it falls back to the feed excerpt and says so.</td>
    <td width="33%" valign="top"><b>Fits the Deck</b><br>D-pad and triggers throughout. Long-press an article for its menu.</td>
  </tr>
</table>

<img src="media/QAM02_settings.png" alt="Settings" height="260"> <img src="media/QAM03_summary_metrics.png" alt="Summary metrics" height="260">

## Using it

| Action | Input |
|---|---|
| Expand an article | A |
| Article menu (peek, summarize, mark read, open, dismiss) | X, or long-press |
| Next / previous page | R2 / L2 |

To turn on summaries, open Settings and enable **AI Summaries**. The model downloads on first use and is cached afterwards.

## Models

| Model | Size | Notes |
|---|---|---|
| Qwen2.5-0.5B | 352 MB | Default. Reliable summaries. |
| Qwen3-0.6B | 397 MB | Newer generation, thinking disabled. Follows instructions better. |
| Gemma 3 270M | 253 MB | Very fast, lighter quality. |
| SmolLM2-360M | 220 MB | Fastest, lowest quality. |

Pick one under **AI Model** in Settings. Models come from Hugging Face and run through a bundled [llamafile](https://github.com/Mozilla-Ocho/llamafile).

## Settings

| Setting | Range | Default |
|---|---|---|
| Refresh interval | 5–120 min | 30 min |
| Article retention | 100–2000 articles | 500 |
| AI personality | analyst, tldr | analyst |
| Allow AI during gaming | on / off | off |
| Temp ceiling | 50–95 °C | 75 °C |
| Summarization cooldown | 5–120 s | 20 s |
| Thermal bonus cooldown | 0–120 s | 30 s |
| Adaptive tokens / threads | on / off | on |
| Typewriter speed | 10–100 chars/s | 30 |
| Long-press delay | 200–1000 ms | 700 ms |

Summaries are blocked when free RAM is under 800 MB or the CPU is above the temp ceiling. When the Deck is within 5 °C of the ceiling, summaries get shorter and use one thread.

## Troubleshooting

Watch the plugin log:

```bash
journalctl -u plugin_loader -f | grep -i deckynews
```

- **News not loading.** Look for a source that keeps failing. Failing sources back off and retry on their own.
- **`Exec format error` when summarizing.** The plugin fixes the binary's permissions on startup. If it persists: `chmod +x ~/homebrew/plugins/DeckyNews/bin/llamafile`
- **`failed to load model`.** The model may not be supported by the bundled llamafile (0.9.3). Switch to a model from the table above.
- **No summaries during games.** Expected. Enable **Allow AI during gaming** to override, or keep the CPU under the temp ceiling.
- **Summary says it used the feed excerpt.** The article site blocked the reader, so the summary is based on the excerpt only.

## Building from source

```bash
pnpm install
pip install -r requirements.txt
pnpm run build            # frontend
python bundle.py          # DeckyNews.zip
python -m pytest          # backend tests
```

How it fits together: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Privacy

No telemetry leaves the device. Feeds and articles are fetched from the sources above, and the model files are downloaded from Hugging Face. Summaries run locally.

## License

BSD-3-Clause. See [LICENSE](LICENSE).

Built with [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) and [Mozilla llamafile](https://github.com/Mozilla-Ocho/llamafile). Default model: [Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF).
