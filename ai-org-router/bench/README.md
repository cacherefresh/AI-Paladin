# bench/

Everything on the "It is not a curve. It is a cliff." slide is generated from
here. No performance number is hand-typed into the deck.

```
bench.py              measure this machine; appends to results.jsonl
project.py            the scaling model; writes projection.json
make_chart.py         renders projection.json -> scaling_chart.svg
results.jsonl         measured runs, append-only
projection.json       derived figures the deck cites
```

## Re-measure after any hardware change

```bash
python3 bench/bench.py --runs 3 --label "egpu-8gb"
python3 bench/project.py        # update the model
python3 bench/make_chart.py     # re-render the chart
```

Then paste the new `scaling_chart.svg` over the `<svg>` block on the scaling
slide of `HUMAN_C_SUITE_DOCUMENTATION/PITCH_DECK.html`.

## Why bandwidth, not FLOPs

Decode reads every weight once per token, so `tok/s ≈ bandwidth / model_bytes`.
`bench.py` back-computes the effective bandwidth the hardware actually
delivered, which is the honest way to compare configurations and the only way
to project a new one.

Baseline measured 2026-08-12: **4.94 tok/s** on a 15.18 GB model =
**75.0 GB/s effective**, on an AMD Ryzen AI 9 HX 370, CPU only, no GPU
offload. Three runs within ±0.01 tok/s.

## Status of the external GPU — read before quoting GPU numbers

**As of the baseline run, no external GPU was attached.** The projections for
every GPU tier are therefore *modelled*, and the deck labels them that way.

What the machine reports:

- The only AMD device present is `1002:150e` — the **integrated Radeon 890M**
  in the Ryzen AI 9 HX 370, with **2 GB** of VRAM carved from system memory.
  That is not an 8 GB discrete card and is far too small to hold this model.
- Thunderbolt/USB4 domains exist (`domain0`, `domain1`) but enumerate **only
  the host routers** — no downstream device, no eGPU enclosure, nothing on the
  USB tree that looks like one.
- Ollama's **ROCm v7.2 runner is installed**, so AMD acceleration will work as
  soon as a supported card is actually visible. The software is not the
  blocker.

To get the eGPU working:

1. Connect and power the enclosure, then `ls /sys/bus/thunderbolt/devices/` —
   a new entry with a `device_name` should appear.
2. If it appears but is unauthorised:
   `echo 1 | sudo tee /sys/bus/thunderbolt/devices/<id>/authorized`
   (some firmware requires approving the device in BIOS/UEFI first).
3. Confirm the kernel bound it: `lspci -nn | grep -i vga` should list a second
   AMD device, and `/sys/class/drm/card*/device/mem_info_vram_total` should
   report ~8 GB on the new card.
4. Restart Ollama so it re-runs GPU discovery, then `ollama ps` — the
   PROCESSOR column should stop saying `100% CPU`.
5. Re-run the benchmark with `--label egpu-8gb`.

## What to expect from 8 GB — and why we would not buy it

The model is 15.18 GB. An 8 GB card holds roughly **46%** of it after
framebuffer and KV-cache overhead, so the other 54% still streams from system
RAM at 75 GB/s — and that half does not get faster no matter what the card is.
Amdahl's law caps the result at **1.8× even with an infinitely fast GPU**; the
realistic figure is **1.3×**, taking a 300-token answer from 61 s to 45 s.

The step change is at **full residency**: a card that fits the whole model
takes the same answer to ~11 s, and the next tier to ~6.5 s. If the goal is a
demo that feels responsive, **VRAM capacity is the specification that matters,
not GPU model or price**. Buy 16 GB minimum; 24 GB gives headroom for context
and a larger model later.

The 8 GB card is still worth benchmarking — a real 1.3× measurement is more
persuasive than a modelled one, and it validates the model's prediction, which
is itself a good thing to be able to show.
