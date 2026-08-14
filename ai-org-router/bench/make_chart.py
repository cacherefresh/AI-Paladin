#!/usr/bin/env python3
"""
Render the hardware-scaling chart as inline SVG, straight from
bench/projection.json. No figure in the deck is typed by hand.

Form: horizontal bars - the job is "compare magnitude across a few named
categories". Colour is EMPHASIS, not categorical: the one measured bar carries
the accent hue, the projections are de-emphasis gray. Every bar is directly
labelled, so identity never rests on colour alone.
"""
import json

d = json.load(open("bench/projection.json"))
rows = d["tiers"]

ACCENT, MUTED = "#2a78d6", "#898781"
INK, DIM, GRID = "#0f1c2e", "#66788f", "#e6ecf3"

W, LEFT, RIGHT = 1080, 178, 108
CLIFF_GAP = 30            # blank band at the residency threshold - the gap IS the cliff
ROW_H, BAR_H, TOP = 44, 21, 40
PLOT_W = W - LEFT - RIGHT
vmax = max(r["seconds_per_answer"] for r in rows)
scale = PLOT_W / (vmax * 1.02)
H = TOP + len(rows) * ROW_H + CLIFF_GAP + 66


def bar(x, y, w, h, fill, r=4):
    """Baseline-anchored bar: square at the axis, 4px rounded at the data end."""
    w = max(w, r + 0.5)
    return (f'<path d="M{x},{y} H{x+w-r} a{r},{r} 0 0 1 {r},{r} '
            f'V{y+h-r} a{r},{r} 0 0 1 -{r},{r} H{x} Z" fill="{fill}"/>')


out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" '
       f'aria-label="Seconds per 300-token answer by hardware tier" '
       f'font-family="ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif">']

# legend - two encodings on screen, so a legend is mandatory
out.append(f'<g font-size="13" fill="{DIM}">'
           f'<rect x="{LEFT}" y="10" width="11" height="11" rx="2.5" fill="{ACCENT}"/>'
           f'<text x="{LEFT+18}" y="20">Measured on this machine</text>'
           f'<rect x="{LEFT+205}" y="10" width="11" height="11" rx="2.5" fill="{MUTED}"/>'
           f'<text x="{LEFT+223}" y="20">Projected from the bandwidth model</text></g>')

# x grid - recessive
for t in range(0, int(vmax) + 10, 10):
    x = LEFT + t * scale
    out.append(f'<line x1="{x:.1f}" y1="{TOP-8}" x2="{x:.1f}" y2="{TOP+len(rows)*ROW_H+CLIFF_GAP-16}" '
               f'stroke="{GRID}" stroke-width="1"/>')
    out.append(f'<text x="{x:.1f}" y="{TOP+len(rows)*ROW_H+CLIFF_GAP+4}" font-size="12" fill="{DIM}" '
               f'text-anchor="middle">{t}s</text>')

cliff_i = next(i for i, r in enumerate(rows) if r["resident_pct"] >= 99)

for i, r in enumerate(rows):
    y = TOP + i * ROW_H + (CLIFF_GAP if i >= cliff_i else 0)
    fill = ACCENT if r["measured"] else MUTED
    w = r["seconds_per_answer"] * scale
    out.append(f'<text x="{LEFT-14}" y="{y+BAR_H-6}" font-size="14.5" fill="{INK}" '
               f'text-anchor="end" font-weight="650">{r["label"]}</text>')
    out.append(f'<g><title>{r["label"]}: {r["seconds_per_answer"]}s per 300-token '
               f'answer, {r["tok_s"]} tok/s, {r["resident_pct"]}% of the model in VRAM</title>'
               + bar(LEFT, y, w, BAR_H, fill) + '</g>')
    # direct label - value and speedup, in ink not in the series colour
    out.append(f'<text x="{LEFT+w+11}" y="{y+BAR_H-6}" font-size="14.5" fill="{INK}" '
               f'font-weight="700">{r["seconds_per_answer"]:.0f}s</text>')
    sub = "baseline" if r["measured"] else f'{r["speedup_x"]:g}x faster'
    out.append(f'<text x="{LEFT+w+11}" y="{y+BAR_H+11}" font-size="11.5" fill="{DIM}">{sub}</text>')
    out.append(f'<text x="{LEFT-14}" y="{y+BAR_H+10}" font-size="11" fill="{DIM}" '
               f'text-anchor="end">{r["resident_pct"]}% of model in VRAM</text>')

# the cliff, drawn in the blank band between partial offload and full residency
cy = TOP + cliff_i * ROW_H + CLIFF_GAP / 2 - 4
out.append(f'<line x1="{LEFT-150}" y1="{cy:.0f}" x2="{W-16}" y2="{cy:.0f}" stroke="#b3261e" '
           f'stroke-width="1.6" stroke-dasharray="7 5"/>')
out.append(f'<rect x="{LEFT+250}" y="{cy-11:.0f}" width="384" height="22" fill="#ffffff"/>')
out.append(f'<text x="{LEFT+262}" y="{cy+4:.0f}" font-size="12.5" fill="#b3261e" '
           f'font-weight="700">THE CLIFF &#183; the model now fits entirely in VRAM</text>')

out.append(f'<text x="{LEFT}" y="{H-30}" font-size="12" fill="{DIM}">'
           f'Seconds to produce a 300-token answer. Measured anchor: '
           f'{d["measured_tok_s"]} tok/s on a {d["model_gb"]} GB model '
           f'= {d["system_bw_gb_s"]} GB/s effective bandwidth.</text>')
out.append(f'<text x="{LEFT}" y="{H-13}" font-size="12" fill="{DIM}">'
           f'Projections assume each class delivers ~70% of its peak bandwidth; '
           f'see bench/project.py.</text>')
out.append('</svg>')

open("bench/scaling_chart.svg", "w").write("\n".join(out))
print("wrote bench/scaling_chart.svg (%d bytes)" % len("\n".join(out)))
