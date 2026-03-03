# LLM Binary Directory

This directory contains the Llamafile binary for on-device LLM inference.

## Required Binary

Place `llamafile` (Linux x64 static binary) in this directory.

## What is Llamafile?

Llamafile is Mozilla's single-file LLM runtime that combines llama.cpp with
Cosmopolitan Libc. It has NO external dependencies (no MKL, no ROCm) and
includes optimized matrix multiplication for both Intel and AMD CPUs.

**Key advantages:**
- ✅ Works on Steam Deck (AMD APU) - no MKL dependency
- ✅ 30-500% faster inference on AMD vs standard llama.cpp
- ✅ Static binary - no shared libraries required
- ✅ CLI-compatible with llama.cpp
- ✅ Smaller bundle size (6MB vs 27MB)

## How to Obtain

### Recommended: Download Pre-built Binary

1. Visit: https://github.com/mozilla-ai/llamafile/releases
2. Download: `llamafile-0.9.3` (or latest version)
3. Place it in this directory as `llamafile`
4. Make executable: `chmod +x llamafile`

### Alternative: Build from Source

```bash
git clone https://github.com/mozilla-ai/llamafile.git
cd llamafile
make -j$(nproc)
cp llamafile /path/to/DeckyNews/bin/
chmod +x /path/to/DeckyNews/bin/llamafile
```

## Verification

```bash
./llamafile --version
./llamafile --help
```

## Model File

The GGUF model file (~300MB) is downloaded separately from HuggingFace Hub
on first use. It is NOT bundled with the plugin.

- Model: Qwen/Qwen2.5-0.5B-Instruct-GGUF
- File: qwen2.5-0.5b-instruct-q4_k_m.gguf
- Location: ~/.local/share/DeckyPlugins/deckynews/runtime/models/

## Legacy Support

The plugin also checks for `llama-cli` (legacy llama.cpp binary) for backwards
compatibility. However, llama-cli built with MKL will NOT work on Steam Deck.

## Troubleshooting

### "Exec format error" on Steam Deck

If llamafile fails with "Exec format error":

1. **Missing executable permissions** (fixed automatically by plugin at runtime):

   Manual fix via SSH:
   ```bash
   chmod +x ~/homebrew/plugins/DeckyNews/bin/llamafile
   ```

2. **Intel CPU libraries conflict** (removed from bundle automatically):

   Manual cleanup:
   ```bash
   cd ~/homebrew/plugins/DeckyNews/bin
   rm -f libggml-cpu-{alderlake,cannonlake,cascadelake,cooperlake,haswell,icelake,ivybridge,sandybridge,sapphirerapids,skylakex,sse42}.so
   ```

3. **APE (Actually Portable Executable) format** (handled automatically by plugin):

   Llamafile uses Mozilla's APE format with a shell script header. The plugin automatically
   runs it via `/bin/sh` to bootstrap the embedded binary. If running manually:
   ```bash
   /bin/sh ~/homebrew/plugins/DeckyNews/bin/llamafile --help
   ```

4. **Check file type**:
   ```bash
   file ~/homebrew/plugins/DeckyNews/bin/llamafile
   # Should output: ELF 64-bit LSB executable, x86-64
   ```

### Plugin Logs

```bash
journalctl -u plugin_loader -f | grep -i deckynews
```

Look for:
- "Found executable llamafile binary: /path/to/llamafile"
- "Fixed permissions for llamafile: /path/to/llamafile"
