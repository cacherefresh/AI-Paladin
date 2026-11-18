#!/usr/bin/env python3
"""
Throughput benchmark for the on-prem node.

Decode on a dense transformer is memory-bandwidth-bound: generating one token
requires reading essentially every weight. So

    tokens/sec  ~=  effective_memory_bandwidth / model_bytes

which means the honest way to talk about "will a GPU make this faster" is to
talk about bandwidth and residency, not about core counts or TFLOPs.

This script measures tokens/sec and back-computes the effective bandwidth the
hardware actually delivered. Run it before and after any hardware change; the
numbers drop straight into the pitch deck.

    python3 bench/bench.py                 # default model, 3 runs
    python3 bench/bench.py --runs 5 --model devstral-small-2:latest
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request

ENDPOINT = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

PROMPTS = [
    "Write a Python function that merges two sorted lists. Code only.",
    "Explain what a race condition is, in four sentences.",
    "Write a SQL query that finds duplicate emails in a users table.",
]


def model_bytes(model: str) -> int:
    try:
        req = urllib.request.Request(ENDPOINT + "/api/tags")
        data = json.load(urllib.request.urlopen(req, timeout=5))
        for m in data.get("models", []):
            if m["name"] == model:
                return m.get("size", 0)
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        pass
    return 0


def placement(model: str) -> str:
    """Where ollama actually put the layers. The whole question, really."""
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True,
                             timeout=10).stdout
        for line in out.splitlines():
            if model.split(":")[0] in line:
                return " ".join(line.split()[3:5])
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def one_run(model: str, prompt: str, num_predict: int) -> dict:
    body = json.dumps({
        "model": model, "prompt": prompt, "stream": False,
        "keep_alive": "60m",
        "options": {"num_predict": num_predict, "temperature": 0.0},
    }).encode()
    req = urllib.request.Request(ENDPOINT + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    d = json.load(urllib.request.urlopen(req, timeout=900))
    wall = time.time() - t0

    eval_count = d.get("eval_count", 0) or 0
    eval_ns = d.get("eval_duration", 0) or 0
    prompt_count = d.get("prompt_eval_count", 0) or 0
    prompt_ns = d.get("prompt_eval_duration", 0) or 0
    return {
        "wall_s": round(wall, 2),
        "gen_tokens": eval_count,
        "gen_tok_s": round(eval_count / (eval_ns / 1e9), 3) if eval_ns else 0.0,
        "prompt_tokens": prompt_count,
        "prompt_tok_s": round(prompt_count / (prompt_ns / 1e9), 1) if prompt_ns else 0.0,
        "ttft_s": round(prompt_ns / 1e9, 2) if prompt_ns else 0.0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="devstral-small-2:latest")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--tokens", type=int, default=120)
    ap.add_argument("--label", default="", help="e.g. 'cpu-only' or 'egpu-8gb'")
    ap.add_argument("--out", default="bench/results.jsonl")
    args = ap.parse_args()

    size = model_bytes(args.model)
    print("\n  model      : %s" % args.model)
    print("  size       : %.2f GB" % (size / 1e9) if size else "  size       : unknown")
    print("  placement  : %s" % placement(args.model))
    print("  warming up ...")
    one_run(args.model, "hi", 1)

    runs = []
    for i in range(args.runs):
        r = one_run(args.model, PROMPTS[i % len(PROMPTS)], args.tokens)
        runs.append(r)
        print("  run %d      : %6.2f tok/s gen | %7.1f tok/s prompt | %5.2fs ttft"
              % (i + 1, r["gen_tok_s"], r["prompt_tok_s"], r["ttft_s"]))

    gen = statistics.median(r["gen_tok_s"] for r in runs)
    pro = statistics.median(r["prompt_tok_s"] for r in runs)
    # Back out the bandwidth the hardware actually delivered.
    bw = gen * size / 1e9 if size else 0.0

    print("\n  MEDIAN generation : %.2f tok/s" % gen)
    print("  MEDIAN prompt     : %.1f tok/s" % pro)
    if bw:
        print("  effective bandwidth: %.1f GB/s  (%.2f tok/s x %.2f GB per token)"
              % (bw, gen, size / 1e9))
    print("  a 300-token answer takes ~%.0f s\n" % (300 / gen if gen else 0))

    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "label": args.label or "unlabelled",
           "model": args.model, "model_bytes": size, "placement": placement(args.model),
           "median_gen_tok_s": gen, "median_prompt_tok_s": pro,
           "effective_bandwidth_gb_s": round(bw, 1), "runs": runs}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "a") as fh:
        fh.write(json.dumps(rec) + "\n")
    print("  appended to %s\n" % args.out)


if __name__ == "__main__":
    main()
