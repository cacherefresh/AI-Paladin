#!/usr/bin/env python3
"""
Fleet economics: mesh grid vs pooled micro datacentre.

Same discipline as project.py - every figure is derived from stated
assumptions, expressed as BANDS rather than false precision, and recomputed
from this file rather than typed into a slide.

THE TWO FACTS THAT DECIDE IT
----------------------------
1. Batching. One weight read serves every concurrent request, so a pooled GPU
   multiplies across many developers. A single-user node can never do this.
2. Utilisation. A developer issues tens of prompts a day at ~30 s each - on the
   order of 6% of a GPU-day. Meshing horsepower buys 100% of the hardware to
   use 6% of it.

WHAT IS *NOT* IN THE CROSSOVER
------------------------------
The gate tier (sentry 45 MB + clerk 0.6B) runs on every developer machine in
BOTH designs and needs no GPU, so it costs the same either way and cancels out
of the comparison. That is the point of tiering it: the security perimeter
scales to 500 desks at no marginal hardware cost.
"""

import json
import math

# ---- assumption bands. Change these; everything downstream follows. -------
ASSUMPTIONS = {
    "mesh_node_usd": (1500, 3000),
    # An engineer-capable desk node: enough VRAM to hold the model (>=16 GB,
    # per the residency cliff in project.py). Below that it is not an engineer
    # node, it is a slower CPU box.

    "pooled_gpu_usd": (8000, 15000),
    # A pooled accelerator with the bandwidth and VRAM to batch effectively.

    "pooled_overhead_pct": (30, 40),
    # Chassis, networking, power, cooling, rack. Applied on top of GPU spend.

    "devs_per_pooled_gpu": (15, 25),
    # Derived from ~6% duty cycle plus headroom for correlated peaks (everyone
    # prompts after standup). THE most sensitive parameter in the model, and
    # the one a pilot should measure first.

    "min_pooled_gpus": 2,
    # You do not build a single-GPU cluster. Two is the floor for redundancy,
    # and it is what sets the crossover: below it, pooling pays for capacity
    # nobody is using yet.
}

TEAM_SIZES = [5, 10, 15, 20, 25, 50, 75, 100, 150, 200, 300, 400, 500]


def mesh_total(n, node_usd):
    return n * node_usd


def pooled_total(n, gpu_usd, overhead_pct, devs_per_gpu, min_gpus):
    gpus = max(min_gpus, math.ceil(n / devs_per_gpu))
    return gpus * gpu_usd * (1 + overhead_pct / 100.0), gpus


def band(n):
    """Return (low, mid, high) capex for each design at team size n."""
    a = ASSUMPTIONS
    mesh = [mesh_total(n, c) for c in a["mesh_node_usd"]]
    # favourable pooled case = cheap GPU, low overhead, many devs per GPU
    p_low, g_low = pooled_total(n, a["pooled_gpu_usd"][0],
                                a["pooled_overhead_pct"][0],
                                a["devs_per_pooled_gpu"][1], a["min_pooled_gpus"])
    p_high, g_high = pooled_total(n, a["pooled_gpu_usd"][1],
                                  a["pooled_overhead_pct"][1],
                                  a["devs_per_pooled_gpu"][0], a["min_pooled_gpus"])
    return {
        "n": n,
        "mesh_low": mesh[0], "mesh_high": mesh[1],
        "mesh_mid": (mesh[0] + mesh[1]) / 2,
        "pooled_low": p_low, "pooled_high": p_high,
        "pooled_mid": (p_low + p_high) / 2,
        "gpus_low": g_low, "gpus_high": g_high,
        "mesh_per_dev": (mesh[0] + mesh[1]) / 2 / n,
        "pooled_per_dev": (p_low + p_high) / 2 / n,
    }


def crossover():
    """Smallest team at which pooled mid-estimate beats mesh mid-estimate."""
    for n in range(2, 1001):
        r = band(n)
        if r["pooled_mid"] <= r["mesh_mid"]:
            return n
    return None


if __name__ == "__main__":
    rows = [band(n) for n in TEAM_SIZES]
    x = crossover()

    print("\n  ASSUMPTIONS (bands)")
    for k, v in ASSUMPTIONS.items():
        print("    %-24s %s" % (k, v))

    print("\n  %5s %22s %22s %10s" % ("team", "mesh capex", "pooled capex", "GPUs"))
    print("  " + "-" * 64)
    for r in rows:
        print("  %5d  $%8.0fk - $%-8.0fk  $%7.0fk - $%-7.0fk  %3d-%-3d"
              % (r["n"], r["mesh_low"]/1000, r["mesh_high"]/1000,
                 r["pooled_low"]/1000, r["pooled_high"]/1000,
                 r["gpus_low"], r["gpus_high"]))

    print("\n  crossover (pooled becomes cheaper): ~%d developers" % x)
    r500 = band(500)
    print("\n  AT 500 DEVELOPERS")
    print("    mesh   : $%.2fM - $%.2fM" % (r500["mesh_low"]/1e6, r500["mesh_high"]/1e6))
    print("    pooled : $%.0fk - $%.0fk  (%d-%d GPUs)"
          % (r500["pooled_low"]/1000, r500["pooled_high"]/1000,
             r500["gpus_low"], r500["gpus_high"]))
    print("    ratio  : pooled is %.1fx - %.1fx cheaper"
          % (r500["mesh_low"]/r500["pooled_high"], r500["mesh_high"]/r500["pooled_low"]))

    env_lo, env_hi = 100_000, 300_000
    fits = env_lo <= r500["pooled_low"] <= env_hi
    print("\n    stated $100k-$300k envelope at 500 seats: %s"
          % ("covered at the FAVOURABLE end only" if fits else "not covered"))
    print("    unfavourable end is $%.0fk - roughly %.1fx the envelope ceiling"
          % (r500["pooled_high"]/1000, r500["pooled_high"]/env_hi))

    json.dump({"assumptions": {k: list(v) if isinstance(v, tuple) else v
                               for k, v in ASSUMPTIONS.items()},
               "crossover_developers": x, "rows": rows},
              open("bench/fleet.json", "w"), indent=2)
    print("\n  wrote bench/fleet.json\n")
