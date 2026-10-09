"""Wykresy sprawdzające, czy pomiary sensorów są rzeczywiście liniowe.

Dla każdego sensora z pomiary.csv:
  - góra: punkty pomiarowe (kolor = węzeł, który je przesłał) + prosta dopasowana
    metodą najmniejszych kwadratów,
  - dół: reszty (pomiar - prosta). Dla idealnej prostej leżą na zerze; ślad po
    zaokrągleniu do 0.001 °C to maksymalnie ±0.0005.
W tytule: nachylenie dopasowane vs NACHYLENIE_A z pliku sensora, R² i max reszta.

Użycie: python wykres_liniowosci.py [pomiary.csv] [wynik.svg]
Tylko biblioteka standardowa (wynik to plik SVG - otwórz w przeglądarce).
"""
import csv
import os
import sys
from collections import defaultdict

from sensor import load_sensor_file

NODE_COLORS = {1: "#1f77b4", 2: "#ff7f0e", 3: "#2ca02c", 4: "#d62728", 5: "#9467bd"}
W, H_DATA, H_RES, GAP = 520, 190, 70, 70
ML, MR, MT = 62, 14, 34


def fit_line(xs, ys):
    """Regresja liniowa y = a*x + b; zwraca (a, b, R²)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    a = sxy / sxx
    b = my - a * mx
    ss_res = sum((y - (a * x + b)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    return a, b, (1 - ss_res / ss_tot) if ss_tot else 1.0


def load(path):
    data = defaultdict(list)           # sensor -> [(seq, temp, węzeł)]
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            data[int(r["sensor"])].append((int(r["seq"]), float(r["temperatura"]),
                                           int(r["wezel"])))
    return data


def declared_slope(sid, folder="sensors"):
    try:
        return load_sensor_file(os.path.join(folder, f"SENSOR{sid:03d}.TXT"))["NACHYLENIE_A"]
    except (OSError, ValueError, KeyError):
        return None


def nice_ticks(lo, hi, n=5):
    step = (hi - lo) / n or 1
    return [lo + i * step for i in range(n + 1)]


def panel(sid, pts, ox, oy):
    pts = sorted(pts)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    a, b, r2 = fit_line(xs, ys)
    res = [y - (a * x + b) for x, y in zip(xs, ys)]
    max_res = max(abs(r) for r in res)
    a0 = declared_slope(sid)

    x0, x1 = min(xs), max(xs)
    ypad = (max(ys) - min(ys)) * 0.08 or 1
    y0, y1 = min(ys) - ypad, max(ys) + ypad
    pw = W - ML - MR

    def sx(x):
        return ox + ML + (x - x0) / ((x1 - x0) or 1) * pw

    def sy(y):
        return oy + MT + (1 - (y - y0) / (y1 - y0)) * H_DATA

    rlim = max(max_res * 1.3, 1e-4)
    ry = oy + MT + H_DATA + 26

    def sr(r):
        return ry + (1 - (r + rlim) / (2 * rlim)) * H_RES

    o = []
    slope_txt = f"a = {a:.5f} °C/s" + (f" (plik: {a0})" if a0 is not None else "")
    o.append(f'<text x="{ox + ML}" y="{oy + 14}" class="t">Sensor {sid:03d}</text>')
    o.append(f'<text x="{ox + ML}" y="{oy + 28}" class="s">{slope_txt}   R² = {r2:.6f}   '
             f'max reszta = {max_res:.4f} °C   n = {len(pts)}</text>')
    # siatka i osie - wykres danych
    for v in nice_ticks(y0, y1, 4):
        o.append(f'<line x1="{ox + ML}" x2="{ox + ML + pw}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" class="g"/>')
        o.append(f'<text x="{ox + ML - 6}" y="{sy(v) + 4:.1f}" class="a" text-anchor="end">{v:.1f}</text>')
    o.append(f'<rect x="{ox + ML}" y="{oy + MT}" width="{pw}" height="{H_DATA}" class="f"/>')
    # prosta dopasowana (pod punktami)
    o.append(f'<line x1="{sx(x0):.1f}" y1="{sy(a * x0 + b):.1f}" x2="{sx(x1):.1f}" '
             f'y2="{sy(a * x1 + b):.1f}" class="fit"/>')
    for (x, y, n) in pts:
        o.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="2.2" fill="{NODE_COLORS.get(n, "#888")}"/>')
    o.append(f'<text x="{ox + 14}" y="{oy + MT + H_DATA / 2}" class="a" '
             f'transform="rotate(-90 {ox + 14} {oy + MT + H_DATA / 2})" text-anchor="middle">T [°C]</text>')
    # reszty
    o.append(f'<rect x="{ox + ML}" y="{ry}" width="{pw}" height="{H_RES}" class="f"/>')
    o.append(f'<line x1="{ox + ML}" x2="{ox + ML + pw}" y1="{sr(0):.1f}" y2="{sr(0):.1f}" class="zero"/>')
    for (x, r) in zip(xs, res):
        o.append(f'<circle cx="{sx(x):.1f}" cy="{sr(r):.1f}" r="1.6" class="rp"/>')
    for v in (-rlim, 0, rlim):
        o.append(f'<text x="{ox + ML - 6}" y="{sr(v) + 4:.1f}" class="a" text-anchor="end">{v:+.4f}</text>')
    o.append(f'<text x="{ox + ML}" y="{ry - 5}" class="a">reszty (pomiar − prosta) [°C]</text>')
    # oś X
    for v in nice_ticks(x0, x1, 5):
        o.append(f'<text x="{sx(v):.1f}" y="{ry + H_RES + 14}" class="a" text-anchor="middle">{v:.0f}</text>')
    o.append(f'<text x="{ox + ML + pw / 2}" y="{ry + H_RES + 28}" class="a" text-anchor="middle">'
             f'numer pomiaru k (czas [s])</text>')
    return "\n".join(o), r2, max_res


def main(argv):
    csv_path = argv[0] if argv else "pomiary.csv"
    out_path = argv[1] if len(argv) > 1 else "zrzuty/6_liniowosc.svg"
    data = {s: p for s, p in load(csv_path).items() if len(p) >= 3}
    if not data:
        print("Za mało danych w", csv_path)
        return 1

    cols = 2
    ph = MT + H_DATA + 26 + H_RES + GAP
    rows = (len(data) + cols - 1) // cols
    total_w, total_h = cols * W, 76 + rows * ph
    nodes = sorted({n for pts in data.values() for (_, _, n) in pts})

    body = []
    summary = []
    for i, sid in enumerate(sorted(data)):
        svg, r2, mr = panel(sid, data[sid], (i % cols) * W, 76 + (i // cols) * ph)
        body.append(svg)
        summary.append((sid, r2, mr))
    legend = "".join(
        f'<circle cx="{ML + 4 + k * 70}" cy="62" r="4" fill="{NODE_COLORS.get(n, "#888")}"/>'
        f'<text x="{ML + 12 + k * 70}" y="66" class="a">węzeł {n}</text>'
        for k, n in enumerate(nodes))

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w} {total_h}" width="{total_w}" font-family="Helvetica, Arial, sans-serif">
<style>
.t{{font-size:14px;font-weight:bold;fill:#222}} .s{{font-size:11px;fill:#444}}
.a{{font-size:10px;fill:#555}} .g{{stroke:#e2e2e2}} .f{{fill:none;stroke:#999}}
.fit{{stroke:#111;stroke-width:1.4;stroke-dasharray:6 3}} .zero{{stroke:#111;stroke-width:1}}
.rp{{fill:#444}} .h{{font-size:18px;font-weight:bold;fill:#222}}
</style>
<rect width="100%" height="100%" fill="#fff"/>
<text x="{ML}" y="26" class="h">Czy pomiary są liniowe? Punkty vs prosta najmniejszych kwadratów</text>
<text x="{ML}" y="44" class="s">Kolor punktu = węzeł, który przesłał pomiar (przeniesienie sensora nie psuje prostej). Linia przerywana = dopasowanie.</text>
{legend}
{chr(10).join(body)}
</svg>
"""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"Zapisano {out_path}")
    for sid, r2, mr in summary:
        print(f"  sensor {sid:03d}: R² = {r2:.6f}   max reszta = {mr:.4f} °C")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
