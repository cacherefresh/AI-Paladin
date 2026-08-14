#!/usr/bin/env python3
"""
Hardware scaling model for the on-prem node.

Autoregressive decode on a dense model is MEMORY-BANDWIDTH-BOUND: producing one
token requires reading essentially every weight once. So

    seconds_per_token = model_bytes / effective_bandwidth

With a GPU too small to hold the model, layers split between VRAM and system
RAM, and the two terms add:

    t = (1-f) * M / BW_sys  +  f * M / BW_gpu          f = fraction resident

That second form is why "just add a GPU" underdelivers. The system-RAM term
does not shrink no matter how fast the GPU is, so partial offload is capped by
Amdahl's law at 1/(1-f). The large win arrives discontinuously, at the point
where the model becomes FULLY resident. It is a cliff, not a ramp.

Every number below is derived from one measured anchor plus a stated bandwidth
assumption per tier. Change an assumption, rerun, and the deck figure changes
with it. Nothing here is hand-typed into a slide.
"""

import json

# ---- measured anchor (bench/results.jsonl, cpu-only-baseline) -------------
MODEL_GB = 15.18          # devstral-small-2, Q4_K_M
MEASURED_TOK_S = 4.94     # median of 3 runs
BW_SYS = MEASURED_TOK_S * MODEL_GB   # back-computed effective system bandwidth
ANSWER_TOKENS = 300       # a realistic answer length for the demo

# ---- tiers. `bw` is ASSUMED effective (not theoretical peak) bandwidth ----
# Effective is typically 55-75% of a spec sheet's peak; these use ~70% of the
# peak for each class, matching the 59% we actually measured on system RAM.
TIERS = [
    {"id": "cpu",   "label": "CPU only",            "vram": 0,
     "bw": None, "note": "measured", "measured": True},
    {"id": "egpu8", "label": "+ 8 GB eGPU",         "vram": 8,
     "bw": 170,  "note": "partial offload - model does not fit"},
    {"id": "gpu16", "label": "16 GB GPU",           "vram": 16,
     "bw": 420,  "note": "first tier where the model is fully resident"},
    {"id": "gpu24", "label": "24 GB GPU",           "vram": 24,
     "bw": 700,  "note": "full residency, headroom for context"},
    {"id": "gpu48", "label": "48 GB class",         "vram": 48,
     "bw": 1400, "note": "full residency, room for a larger model"},
]

VRAM_OVERHEAD_GB = 1.0    # framebuffer + KV cache + runtime, before weights


def resident_fraction(vram_gb: float) -> float:
    if vram_gb <= 0:
        return 0.0
    usable = max(0.0, vram_gb - VRAM_OVERHEAD_GB)
    return min(1.0, usable / MODEL_GB)


def project(tier: dict) -> dict:
    if tier.get("measured"):
        tok_s = MEASURED_TOK_S
        f = 0.0
        ceiling = None
    else:
        f = resident_fraction(tier["vram"])
        t = (1 - f) * MODEL_GB / BW_SYS + f * MODEL_GB / tier["bw"]
        tok_s = 1.0 / t
        # Amdahl ceiling: infinitely fast GPU, same residency fraction.
        ceiling = 1.0 / ((1 - f) * MODEL_GB / BW_SYS) if f < 1 else None

    return {
        "id": tier["id"], "label": tier["label"], "vram_gb": tier["vram"],
        "assumed_bw_gb_s": tier["bw"], "resident_pct": round(100 * f),
        "tok_s": round(tok_s, 1),
        "seconds_per_answer": round(ANSWER_TOKENS / tok_s, 1),
        "speedup_x": round(tok_s / MEASURED_TOK_S, 1),
        "amdahl_ceiling_tok_s": round(ceiling, 1) if ceiling else None,
        "note": tier["note"], "measured": bool(tier.get("measured")),
    }


if __name__ == "__main__":
    rows = [project(t) for t in TIERS]
    print("\n  measured anchor: %.2f tok/s on %.2f GB => %.1f GB/s effective "
          "system bandwidth\n" % (MEASURED_TOK_S, MODEL_GB, BW_SYS))
    print("  %-14s %6s %8s %8s %9s %8s %s"
          % ("tier", "VRAM", "resident", "tok/s", "300 tok", "speedup", "ceiling"))
    print("  " + "-" * 78)
    for r in rows:
        print("  %-14s %5sG %7s%% %8.1f %8.1fs %7.1fx %s"
              % (r["label"], r["vram_gb"] or "-", r["resident_pct"], r["tok_s"],
                 r["seconds_per_answer"], r["speedup_x"],
                 ("%.1f tok/s" % r["amdahl_ceiling_tok_s"])
                 if r["amdahl_ceiling_tok_s"] else "-"))
    print()
    for r in rows:
        print("  %-14s %s" % (r["label"], r["note"]))
    with open("bench/projection.json", "w") as fh:
        json.dump({"model_gb": MODEL_GB, "measured_tok_s": MEASURED_TOK_S,
                   "system_bw_gb_s": round(BW_SYS, 1),
                   "answer_tokens": ANSWER_TOKENS, "tiers": rows}, fh, indent=2)
    print("\n  wrote bench/projection.json\n")
