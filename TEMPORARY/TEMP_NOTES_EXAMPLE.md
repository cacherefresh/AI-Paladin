# Scratch - on-prem model picker + internet access toggle

**Gitignored.** Session staging only. See `AGENTS.md`.
Last touched: 2026-11-19

## Ask (Rob)
- Dropdown for the on-prem model in the dashboard, labelled by role.
  Labels (multi): `coding`, `research + computer use`, `research / planning`.
- No Chinese models. Prefer Hugging Face where possible.
- Internet toggle for the on-prem model, default READ-ONLY:
  - `off`        never-leave-on-prem, label "no-external-network-io" (local file IO still works)
  - `read`       RAG-LLM: search + fetch, GET only   <- default
  - `readwrite`  POST + session cookies, can sign in

## Hardware (measured)
- Ryzen AI 9 HX 370, Radeon 890M iGPU (gfx1150), 91 GiB RAM, 1.6 TB free.
- Ollama 0.30.10 drops the iGPU ("set OLLAMA_IGPU_ENABLE=1"). All CPU today.
- devstral-small-2 is dense 24B -> ~5 tok/s. MoE with ~3-5B active is the win.

## Models (licence-checked against ROADMAP s8 Apache-2.0/MIT allowlist)
| model | vendor | active | labels | licence |
|---|---|---|---|---|
| gpt-oss:120b | OpenAI US | 5.1B | research/planning, coding | Apache-2.0 |
| gpt-oss:20b | OpenAI US | 3.6B | research/planning | Apache-2.0 |
| gemma4:26b | Google US | ~4B | research+computer, research/planning | Apache-2.0 |
| flint:40b | Recursive US | 2.5B | coding | Apache-2.0 |
| devstral-small-2 | Mistral FR | 24B dense | coding | Apache-2.0 |
| Laguna XS 2.1 (HF) | Poolside | 3B | coding | OpenMDW-1.1 -> disabled |
| Nemotron 3.5 Lightning (HF) | NVIDIA | 3B | research | OpenMDW-1.1 -> disabled |

## Build plan
1. `models/catalog.yaml` - data; licence allowlist; HF alternative per entry.
2. `nodes/web_tools.py` - search/fetch/submit. Enforced in code:
   method allowlist per mode, public-IP only, outbound text through the
   keyword gate, per-task call cap, cookies only in readwrite.
3. Worker -> /api/chat with tools; RAG pre-search when prompt needs live data;
   `off` runs under egress_guard.sealed_thread (socket-level, process scope).
4. Server: GET/POST /api/onprem; sovereign forces `off`; protected-IP task
   downgrades readwrite -> read; selection persisted to config/local_models.yaml.
5. UI: dropdown + label chips + 3-way toggle; readwrite needs a confirm.
6. Docs: nodes/README.md, docs/MODELS.md.

## Open items for Rob
- Clerk/sentry subagents still use qwen3:0.6b (Alibaba). Not swapped: it is
  part of the gate; replacing it needs a re-bench.
- iGPU: needs `OLLAMA_IGPU_ENABLE=1` in the ollama systemd unit (sudo).

## Status 2026-11-19 evening
- Built and tested end to end: catalog, picker, 3-way internet toggle,
  web_tools gates, worker tool loop + RAG pre-search, docs/MODELS.md.
- Measured: gpt-oss:20b 14-31 tok/s vs devstral 4.9, live search answered
  "latest Python" correctly (3.15.2) with 2 GETs.
- Downloads running in background: gemma4:26b, flint:40b, gpt-oss:120b.
  They appear in the dropdown on their own once pulled (UI polls every 5s).
- Test runs appended to ai-org-router/logs/*.jsonl (tracked as demo
  evidence; they were already modified before this session).
- Nothing committed.

---

## Hardware tiers + "usable here" - draft table (2026-11-19, for review)

### What this machine has (probed, not assumed)
| Item | Value | Source |
|---|---|---|
| CPU | Ryzen AI 9 HX 370, 24 threads | lscpu |
| RAM | 91.9 GiB | /proc/meminfo |
| iGPU | Radeon 890M (gfx1150), 2.1 GB carve-out + 49.4 GB GTT (borrowed RAM) | /sys/class/drm/card1 |
| NPU | XDNA 2, driver `amdxdna` loaded, `/dev/accel/accel0` present, **unused** | lsmod |
| Discrete GPU / GDDR | none | lspci |
| Ollama | CPU only (drops iGPU without OLLAMA_IGPU_ENABLE=1); cannot use NPU at all | journalctl |

Note: the "8 GB" is not what the kernel reports. The iGPU carve-out is 2.1 GB.
Either BIOS UMA is set lower than expected or the 8 GB is something else.

### Draft model table
Requirements = weights + ~4-8 GB for context and OS. "RAM path" is CPU or
iGPU/unified memory. "GDDR path" is a discrete card holding the whole model.

| Model | Vendor | Role labels | Tier label | Min RAM (no dGPU) | Min GDDR (dGPU) | NPU | Usable here | Status |
|---|---|---|---|---|---|---|---|---|
| gpt-oss 20B | OpenAI | research / planning | economical laptop | 16 GB | 16 GB | optional (FastFlowLM, ~19 tok/s reported, unverified) | yes, 14-31 tok/s measured | installed |
| Gemma 4 26B | Google | research + computer use, research / planning | economical laptop | 24 GB (32 rec.) | 24 GB | not supported yet | yes | installed |
| Flint 40B | Recursive | coding | AMD Halo / gaming rig | 32 GB | 24 GB (tight) / 32 GB | no | yes | downloading |
| Devstral Small 2 | Mistral | coding | AMD Halo / gaming rig | 24 GB | 24 GB (16 GB w/ short ctx) | no | yes, but slow: 4.9 tok/s (dense) | installed |
| gpt-oss 120B | OpenAI | research / planning, coding | AMD Halo / gaming rig | 80 GB (96 rec., Strix Halo 128 GB ~30 tok/s) | 80 GB (workstation only) | no | yes, RAM-bound | queued |
| Laguna XS 2.1 | Poolside | coding | AMD Halo / gaming rig | 28 GB | 24 GB | no | n/a - licence-disabled | not pulled |
| Nemotron 3.5 Lightning | NVIDIA | research / planning | economical laptop | 24 GB | 24 GB | no | n/a - licence-disabled | not pulled |

Draft tier rule: "economical laptop" = runs at >= 10 tok/s on a 32 GB laptop
with no discrete GPU. Everything else = "AMD Halo / gaming rig".
Draft usable rule: weights + overhead fit in the best memory pool detected
(GDDR, else unified/GTT, else RAM) at the chosen budget.
NPU: no model here REQUIRES one. Ollama cannot use it.

Plan for building this: see the Claude plan (plan mode), not this file.
