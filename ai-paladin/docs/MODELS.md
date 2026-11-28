# On-prem models

How the dashboard's model picker is fed, what is in it, and why.
The catalog itself is `models/catalog.yaml`.

## Rules for the catalog

- **Open-weight and OSI-licensed only.** The catalog's `license_allowlist`
  is Apache-2.0 and MIT. Other entries are listed but disabled, with the reason.
- **No models from Chinese labs.** Owner's decision, 2026-11-19. This rules
  out Qwen, DeepSeek, GLM, Kimi and MiniMax, and fine-tunes built on them.
- **The server never downloads a model.** Pulling is egress. The picker
  shows the pull command; a person runs it.
- Labels describe what a model is good for. A model can carry several:
  `better for coding`, `research + computer use`, `research / planning`.

## Picks for this machine class

Ryzen AI 9 HX 370, Radeon 890M iGPU, 96 GB RAM. Decode speed is bound by
memory bandwidth, so the number that matters is **active** parameters.
A dense 24B reads all 24B per token; a mixture-of-experts model with 3-5B
active reads only those.

| Model | Vendor | Active | Labels | Download |
|---|---|---|---|---|
| gpt-oss 120B | OpenAI | 5.1B of 117B | research / planning, coding | 65.4 GB |
| gpt-oss 20B (default) | OpenAI | 3.6B of 21B | research / planning | 13.8 GB |
| Gemma 4 26B | Google | ~4B of 26B | research + computer use, research / planning | 18.7 GB |
| Flint 40B | Recursive | ~2.5B of 40B | coding | 22.9 GB |
| Devstral Small 2 | Mistral AI | 24B dense | coding | 15.2 GB |

Measured on this machine, CPU only:

| Model | Tokens/s |
|---|---|
| Devstral Small 2 | 4.9 |
| gpt-oss 20B | 14-31 |

Gemma 4 is the only allowlisted pick with both vision and tool calling, which
is what computer use needs. AI-Paladin itself drives the web only, through
`ai_paladin/nodes/web_tools.py`; it does not drive a desktop.

gpt-oss 120B takes most of the RAM. Switching models in the dashboard unloads
the previous one first.

Listed but disabled for licence: Poolside Laguna XS 2.1 and NVIDIA Nemotron
3.5 Lightning, both OpenMDW-1.1.

## Pulling from Hugging Face

Ollama pulls GGUF files straight from Hugging Face. Every catalog entry has a
`huggingface` field with the repo:

```bash
ollama pull hf.co/ggml-org/gpt-oss-20b-GGUF
ollama pull hf.co/unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q4_K_M
```

The Ollama library tags are the default because Ollama ships a tested chat
template and tool-call parser with them. A GGUF from Hugging Face uses the
template embedded in the file, and tool calling is less reliable. Either way
the weights run on the same CPU or iGPU backend.

## Using the iGPU

Ollama 0.30 skips integrated GPUs by default. The startup log says
`dropping integrated GPU; to enable, set OLLAMA_IGPU_ENABLE=1`. To try it:

```bash
sudo systemctl edit ollama
# add:
# [Service]
# Environment="OLLAMA_IGPU_ENABLE=1"
sudo systemctl restart ollama
ollama ps    # PROCESSOR column should show GPU
```

The iGPU shares system RAM, so it mainly speeds up prompt processing. Decode
is still bound by the same memory bandwidth. Benchmark with `bench/bench.py`
before and after, and keep whichever is faster.

## Not done

- The sentry/clerk tier still uses `qwen3:0.6b` (Alibaba). It is part of the
  keyword gate's advisory layer, so replacing it needs a re-bench of gate
  accuracy first.
- Hardware probe and fit colouring (ROADMAP section 8, phases 1-2).
