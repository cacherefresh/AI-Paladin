#!/usr/bin/env python3
"""
Render the mesh-vs-pooled crossover chart from bench/fleet.json.

Form: two series over a continuous x -> line chart with a shaded band for each
assumption range. Colour is CATEGORICAL (two designs, neither is "good" or
"bad"), slots 1 and 2 of the validated palette: blue #2a78d6 / orange #eb6834,
ALL CHECKS PASS at CVD dE 24.7. Legend is mandatory at two series and both
lines are direct-labelled, so identity never rests on colour.

Y is capex PER DEVELOPER, which is what makes the argument visible: mesh is
flat (you buy the same box for every desk) while pooled declines (each card is
amortised across more people). The crossing point is the whole slide.
"""
import json, math

d = json.load(open("bench/fleet.json"))
rows = d["rows"]
XO = d["crossover_developers"]

MESH, POOL = "#2a78d6", "#eb6834"
INK, DIM, GRID = "#0f1c2e", "#66788f", "#e6ecf3"

W, H = 1080, 410
L, Rt, T, B = 82, 150, 46, 84
PW, PH = W - L - Rt, H - T - B

xs = [r["n"] for r in rows]
lx0, lx1 = math.log10(min(xs)), math.log10(max(xs))
# Ceiling must clear the pooled curve at the SMALLEST team, where a two-GPU
# floor is spread over five people (~$6.3k/dev). Clipping it would hide the
# very thing this chart exists to show: pooling is punitively expensive until
# you can fill a cluster.
ymax = 7000.0


def px(n):   return L + (math.log10(n) - lx0) / (lx1 - lx0) * PW
def py(v):   return T + PH - min(v, ymax) / ymax * PH   # ymax clears all data


def series(key_lo, key_hi, key_mid):
    lo = [(px(r["n"]), py(r[key_lo] / r["n"])) for r in rows]
    hi = [(px(r["n"]), py(r[key_hi] / r["n"])) for r in rows]
    mid = [(px(r["n"]), py(r[key_mid] / r["n"])) for r in rows]
    return lo, hi, mid


def path(pts):
    return "M" + " L".join("%.1f,%.1f" % p for p in pts)


def band(lo, hi):
    return "M" + " L".join("%.1f,%.1f" % p for p in lo) + \
           " L" + " L".join("%.1f,%.1f" % p for p in reversed(hi)) + " Z"


o = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" '
     'aria-label="Capex per developer by team size, mesh versus pooled" '
     'font-family="ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif">' % (W, H)]

# legend
o.append('<g font-size="13.5" fill="%s">' % DIM)
o.append('<rect x="%d" y="12" width="12" height="12" rx="3" fill="%s"/>' % (L, MESH))
o.append('<text x="%d" y="22">Mesh &#8212; a node per developer</text>' % (L + 19))
o.append('<rect x="%d" y="12" width="12" height="12" rx="3" fill="%s"/>' % (L + 260, POOL))
o.append('<text x="%d" y="22">Pooled &#8212; shared micro datacentre</text>' % (L + 279))
o.append('</g>')

# y grid
for v in range(0, int(ymax) + 1, 1000):
    y = py(v)
    o.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="1"/>'
             % (L, y, L + PW, y, GRID))
    o.append('<text x="%d" y="%.1f" font-size="12" fill="%s" text-anchor="end">$%s</text>'
             % (L - 10, y + 4, DIM, ("%.1fk" % (v / 1000)) if v else "0"))
o.append('<text x="%d" y="%.1f" font-size="12" fill="%s" text-anchor="end" '
         'font-weight="700">$/dev</text>' % (L - 10, T - 14, DIM))

# x ticks
for n in (5, 10, 25, 50, 100, 200, 500):
    x = px(n)
    o.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="1"/>'
             % (x, T, x, T + PH, GRID))
    o.append('<text x="%.1f" y="%d" font-size="12.5" fill="%s" text-anchor="middle">%d</text>'
             % (x, T + PH + 22, DIM, n))
o.append('<text x="%.1f" y="%d" font-size="12.5" fill="%s" text-anchor="middle" '
         'font-weight="700">developers (log scale)</text>' % (L + PW / 2, T + PH + 46, DIM))

# bands then lines
for (klo, khi, kmid, col) in ((("mesh_low", "mesh_high", "mesh_mid", MESH)),
                              (("pooled_low", "pooled_high", "pooled_mid", POOL))):
    lo, hi, mid = series(klo, khi, kmid)
    o.append('<path d="%s" fill="%s" opacity="0.13"/>' % (band(lo, hi), col))
    o.append('<path d="%s" fill="none" stroke="%s" stroke-width="2.5" '
             'stroke-linejoin="round"/>' % (path(mid), col))

# crossover
cx = px(XO)
o.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#b3261e" '
         'stroke-width="1.6" stroke-dasharray="6 5"/>' % (cx, T - 4, cx, T + PH))
o.append('<rect x="%.1f" y="%d" width="196" height="21" rx="4" fill="#ffffff"/>'
         % (cx + 7, T + 2))
o.append('<text x="%.1f" y="%d" font-size="12.5" font-weight="700" fill="#b3261e">'
         'CROSSOVER &#183; ~%d developers</text>' % (cx + 13, T + 17, XO))

# direct labels at the right edge
r500 = rows[-1]
o.append('<text x="%.1f" y="%.1f" font-size="13.5" font-weight="700" fill="%s">Mesh</text>'
         % (L + PW + 10, py(r500["mesh_mid"] / 500) + 4, MESH))
o.append('<text x="%.1f" y="%.1f" font-size="11.5" fill="%s">~$2.2k/dev, flat</text>'
         % (L + PW + 10, py(r500["mesh_mid"] / 500) + 20, DIM))
o.append('<text x="%.1f" y="%.1f" font-size="13.5" font-weight="700" fill="%s">Pooled</text>'
         % (L + PW + 10, py(r500["pooled_mid"] / 500) + 4, POOL))
o.append('<text x="%.1f" y="%.1f" font-size="11.5" fill="%s">~$0.9k/dev at 500</text>'
         % (L + PW + 10, py(r500["pooled_mid"] / 500) + 20, DIM))

o.append('<text x="%d" y="%d" font-size="11.5" fill="%s">Capex per developer. Shaded '
         'bands are the full assumption range; lines are the midpoint. '
         'Gate tier excluded &#8212; it needs no GPU and costs the same either way.'
         '</text>' % (L, H - 10, DIM))
o.append('</svg>')

open("bench/fleet_chart.svg", "w").write("\n".join(o))
print("wrote bench/fleet_chart.svg")
