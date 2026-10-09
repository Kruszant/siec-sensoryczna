"""Wizualizacje i weryfikacja danych z symulacji (dane/pomiary.csv, dane/zdarzenia.csv).

Tworzy w folderze wizualizacje/ pliki SVG (otwórz w przeglądarce) i tekstowe
podsumowanie dane/podsumowanie.txt:

  1_liniowosc.svg   - punkty vs prosta najmniejszych kwadratów + reszty (wykres_liniowosci.py)
  2_os_czasu.svg    - oś czasu: który sensor w którym węźle, przerwy = awarie/odłączenia,
                      trójkąty = przeniesienia, szare pasy = węzeł wyłączony
  3_statystyki.svg  - obciążenie węzłów w czasie, czasy trwania awarii,
                      dostępność sensorów, liczba przeniesień

Weryfikacja liniowości: R², nachylenie dopasowane vs NACHYLENIE_A z pliku oraz
sprawdzenie, czy pierwszy pomiar mieści się w przedziale wynikającym z
T_START_MIN/MAX i PRZESUNIECIE_MIN/MAX.

Użycie: python wizualizacje.py [folder_danych=dane] [folder_wyjsciowy=wizualizacje]
"""
import csv
import os
import sys
from collections import Counter, defaultdict

import wykres_liniowosci as wl
from sensor import load_sensor_file

C = wl.NODE_COLORS
GRAY = "#bbbbbb"
STYLE = """<style>
text{font-family:Helvetica,Arial,sans-serif;fill:#333} .h{font-size:17px;font-weight:bold}
.s{font-size:11px;fill:#555} .a{font-size:10px;fill:#555} .g{stroke:#e4e4e4}
.f{fill:none;stroke:#999} .b{font-size:12px;font-weight:bold}
</style>"""


# --------------------------------------------------------------------------
# analiza danych
# --------------------------------------------------------------------------
def read_events(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def analyze(pts):
    """pts = [(seq, temp, węzeł)] jednego sensora -> segmenty, awarie, przeniesienia.

    Segment = ciągły odcinek w jednym węźle (kolejne seq różnią się o 1).
    Awaria  = przeskok numeru pomiaru > 1 (sensor mierzył, ale nie był połączony).
    Przeniesienie = zmiana węzła między kolejnymi pomiarami (z przerwą lub bez)."""
    pts = sorted(pts)
    segs, outages, moves = [], [], []
    start = prev = pts[0]
    for cur in pts[1:]:
        gap = cur[0] - prev[0] - 1
        if gap > 0:
            outages.append((prev[0], cur[0], gap))
        if cur[2] != prev[2]:
            moves.append((cur[0], prev[2], cur[2]))
        if gap > 0 or cur[2] != prev[2]:
            segs.append((start[0], prev[0], prev[2]))
            start = cur
        prev = cur
    segs.append((start[0], prev[0], prev[2]))
    return segs, outages, moves


def node_downtimes(events, t_end):
    """Przedziały czasu, w których węzeł był poza siecią (z zdarzenia.csv)."""
    bands, down = defaultdict(list), {}
    for e in events:
        n, t = e["wezel"], float(e["t_sym"])
        if e["typ"] == "wezel_opuscil" and n and n not in down:
            down[n] = t
        elif e["typ"] == "wezel_dolaczyl" and n in down:
            bands[int(n)].append((down.pop(n), t))
    for n, t in down.items():
        bands[int(n)].append((t, t_end))
    return bands


def verify_start(sid, a, b_at_seq1):
    """Czy T(seq=1) = T_START + A*X0 mieści się w dopuszczalnym przedziale pliku?"""
    try:
        c = load_sensor_file(os.path.join("sensors", f"SENSOR{sid:03d}.TXT"))
    except (OSError, ValueError):
        return None
    cand = [c["T_START_MIN"] + a * c["PRZESUNIECIE_MIN"], c["T_START_MIN"] + a * c["PRZESUNIECIE_MAX"],
            c["T_START_MAX"] + a * c["PRZESUNIECIE_MIN"], c["T_START_MAX"] + a * c["PRZESUNIECIE_MAX"]]
    return min(cand) - 0.01 <= b_at_seq1 <= max(cand) + 0.01, (min(cand), max(cand))


# --------------------------------------------------------------------------
# rysowanie
# --------------------------------------------------------------------------
class Axis:
    def __init__(self, v0, v1, p0, p1):
        self.v0, self.v1, self.p0, self.p1 = v0, v1, p0, p1

    def __call__(self, v):
        return self.p0 + (v - self.v0) / ((self.v1 - self.v0) or 1) * (self.p1 - self.p0)


def timeline(data, bands, t_end, path):
    """Oś czasu: wiersz na sensor (kolor = węzeł), wiersz na węzeł (kiedy był aktywny)."""
    ML, MR, MT, RH = 90, 20, 90, 28
    W = 1040
    sids, nids = sorted(data), sorted(C)[:4]
    ax = Axis(0, t_end, ML, W - MR)
    H = MT + (len(sids) + len(nids)) * RH + 90
    o = [f'<text x="{ML}" y="26" class="h">Oś czasu: gdzie był każdy sensor, awarie i przeniesienia</text>',
         f'<text x="{ML}" y="44" class="s">Kolor odcinka = węzeł, który odbierał dane. Przerwa = sensor odłączony (losowo lub ręcznie). '
         f'▲ = przeniesienie do innego węzła. Szary pas = węzeł wyłączony.</text>']
    for k, n in enumerate(nids):                                   # legenda
        o.append(f'<rect x="{ML + k * 90}" y="56" width="14" height="10" fill="{C[n]}"/>'
                 f'<text x="{ML + 20 + k * 90}" y="65" class="a">węzeł {n}</text>')
    y_sensors = MT
    y_nodes = MT + len(sids) * RH + 34
    # pasy wyłączonych węzłów (tło wierszy sensorów) + siatka czasu
    for v in range(0, int(t_end) + 1, 25):
        o.append(f'<line x1="{ax(v):.1f}" x2="{ax(v):.1f}" y1="{MT - 6}" y2="{y_nodes + len(nids) * RH}" class="g"/>'
                 f'<text x="{ax(v):.1f}" y="{y_nodes + len(nids) * RH + 14}" class="a" text-anchor="middle">{v}</text>')
    for n, bl in bands.items():
        for (t0, t1) in bl:
            o.append(f'<rect x="{ax(t0):.1f}" y="{MT - 6}" width="{ax(t1) - ax(t0):.1f}" '
                     f'height="{len(sids) * RH + 8}" fill="{GRAY}" opacity="0.35"/>'
                     f'<text x="{ax(t0) + 3:.1f}" y="{MT - 10}" class="a">węzeł {n} wyłączony</text>')
    for i, sid in enumerate(sids):
        y = y_sensors + i * RH
        o.append(f'<text x="{ML - 8}" y="{y + 14}" class="b" text-anchor="end">Sensor {sid:03d}</text>')
        segs, outs, moves = analyze(data[sid])
        for (a, b, n) in segs:
            o.append(f'<rect x="{ax(a):.1f}" y="{y + 4}" width="{max(ax(b) - ax(a), 1.5):.1f}" height="14" fill="{C.get(n, "#888")}"/>')
        for (t, n0, n1) in moves:
            o.append(f'<path d="M{ax(t):.1f} {y + 1} l-4 -7 l8 0 z" fill="#111"/>')
    o.append(f'<text x="{ML - 8}" y="{y_nodes - 8}" class="s" text-anchor="end">aktywność węzłów</text>')
    for j, n in enumerate(nids):                                    # wiersze węzłów
        y = y_nodes + j * RH
        o.append(f'<text x="{ML - 8}" y="{y + 14}" class="b" text-anchor="end">Węzeł {n}</text>'
                 f'<rect x="{ax(0):.1f}" y="{y + 6}" width="{ax(t_end) - ax(0):.1f}" height="10" fill="{C[n]}" opacity="0.85"/>')
        for (t0, t1) in bands.get(n, []):
            o.append(f'<rect x="{ax(t0):.1f}" y="{y + 5}" width="{ax(t1) - ax(t0):.1f}" height="12" fill="#fff"/>'
                     f'<rect x="{ax(t0):.1f}" y="{y + 5}" width="{ax(t1) - ax(t0):.1f}" height="12" fill="none" stroke="{C[n]}" stroke-dasharray="3 2"/>')
    o.append(f'<text x="{(ML + W - MR) / 2}" y="{H - 24}" class="a" text-anchor="middle">czas symulacji [s]</text>')
    write(path, W, H, o)


def stats_chart(data, events, bands, t_end, path):
    """4 panele: obciążenie węzłów, czasy awarii, dostępność, przeniesienia."""
    W, H = 1040, 760
    pw, ph = 440, 250
    o = [f'<text x="40" y="28" class="h">Statystyki: obciążenie węzłów, awarie, dostępność, przeniesienia</text>']
    sids = sorted(data)

    # --- (a) liczba sensorów w węźle w czasie (z segmentów) ---
    ox, oy = 70, 80
    steps = int(t_end) - 3          # bez końcówki (zamykanie sieci po symulacji)
    load = {n: [0] * (steps + 1) for n in range(1, 5)}
    for sid in sids:
        for (a, b, n) in analyze(data[sid])[0]:
            for t in range(int(a), min(int(b), steps) + 1):
                if n in load:
                    load[n][t] += 1
    ymax = max(max(v) for v in load.values()) + 1
    ax, ay = Axis(0, steps, ox, ox + pw), Axis(0, ymax, oy + ph, oy)
    o.append(f'<text x="{ox}" y="{oy - 14}" class="b">(a) Liczba sensorów w każdym węźle w czasie</text>')
    for v in range(0, ymax + 1):
        o.append(f'<line x1="{ox}" x2="{ox + pw}" y1="{ay(v):.1f}" y2="{ay(v):.1f}" class="g"/>'
                 f'<text x="{ox - 6}" y="{ay(v) + 4:.1f}" class="a" text-anchor="end">{v}</text>')
    for n, bl in bands.items():
        for (t0, t1) in bl:
            o.append(f'<rect x="{ax(t0):.1f}" y="{oy}" width="{ax(t1) - ax(t0):.1f}" height="{ph}" fill="{GRAY}" opacity="0.3"/>')
    for n in range(1, 5):
        pts = " ".join(f"{ax(t):.1f},{ay(load[n][t]):.1f}" for t in range(steps + 1))
        o.append(f'<polyline points="{pts}" fill="none" stroke="{C[n]}" stroke-width="1.6"/>')
        o.append(f'<rect x="{ox + 200 + n * 55}" y="{oy - 24}" width="10" height="10" fill="{C[n]}"/>'
                 f'<text x="{ox + 214 + n * 55}" y="{oy - 15}" class="a">węzeł {n}</text>')
    for v in range(0, steps + 1, 50):
        o.append(f'<text x="{ax(v):.1f}" y="{oy + ph + 14}" class="a" text-anchor="middle">{v}</text>')
    o.append(f'<text x="{ox + pw / 2}" y="{oy + ph + 30}" class="a" text-anchor="middle">czas symulacji [s] (szary pas = węzeł wyłączony)</text>')

    # --- (b) histogram czasów trwania przerw ---
    ox2 = 580
    durs = [g for sid in sids for (_, _, g) in analyze(data[sid])[1]]
    cap = 12
    cnt = Counter(min(d, cap + 1) for d in durs)
    cmax = max(cnt.values()) + 1 if cnt else 1
    bx, by = Axis(0, cap + 2, ox2, ox2 + pw), Axis(0, cmax, oy + ph, oy)
    o.append(f'<text x="{ox2}" y="{oy - 14}" class="b">(b) Czas trwania przerw w danych (n = {len(durs)})</text>')
    for v in range(0, cmax + 1, max(1, cmax // 5)):
        o.append(f'<line x1="{ox2}" x2="{ox2 + pw}" y1="{by(v):.1f}" y2="{by(v):.1f}" class="g"/>'
                 f'<text x="{ox2 - 6}" y="{by(v) + 4:.1f}" class="a" text-anchor="end">{v}</text>')
    o.append(f'<rect x="{bx(3):.1f}" y="{oy}" width="{bx(9) - bx(3):.1f}" height="{ph}" fill="#2ca02c" opacity="0.10"/>'
             f'<text x="{bx(3) + 4:.1f}" y="{oy + 12}" class="a">zakres losowych odłączeń z plików (3-8 s)</text>')
    for d in range(1, cap + 2):
        c = cnt.get(d, 0)
        o.append(f'<rect x="{bx(d) + 2:.1f}" y="{by(c):.1f}" width="{bx(d + 1) - bx(d) - 4:.1f}" height="{oy + ph - by(c):.1f}" fill="#1f77b4"/>')
        o.append(f'<text x="{(bx(d) + bx(d + 1)) / 2:.1f}" y="{oy + ph + 14}" class="a" text-anchor="middle">{d if d <= cap else str(cap + 1) + "+"}</text>')
    o.append(f'<text x="{ox2 + pw / 2}" y="{oy + ph + 30}" class="a" text-anchor="middle">długość przerwy [s] (przerwy z awarii węzła i ręcznych w prawym końcu)</text>')

    # --- (c) dostępność sensorów ---
    ox, oy = 70, 450
    avail = {}
    for sid in sids:
        seqs = [p[0] for p in data[sid]]
        avail[sid] = len(seqs) / (max(seqs) - min(seqs) + 1) * 100
    cx = Axis(0, 100, ox + 60, ox + pw)
    o.append(f'<text x="{ox}" y="{oy - 14}" class="b">(c) Dostępność sensorów [% sekund z odebranym pomiarem]</text>')
    for i, sid in enumerate(sids):
        y = oy + i * 34
        o.append(f'<text x="{ox + 54}" y="{y + 15}" class="a" text-anchor="end">Sensor {sid:03d}</text>'
                 f'<rect x="{cx(0)}" y="{y + 3}" width="{cx(100) - cx(0)}" height="18" fill="#eee"/>'
                 f'<rect x="{cx(0)}" y="{y + 3}" width="{cx(avail[sid]) - cx(0):.1f}" height="18" fill="#2ca02c"/>'
                 f'<text x="{cx(avail[sid]) - 4:.1f}" y="{y + 16}" class="a" text-anchor="end" style="fill:#fff">{avail[sid]:.1f}%</text>')

    # --- (d) przeniesienia i przerwy na sensor ---
    ox2 = 580
    nm = {sid: len(analyze(data[sid])[2]) for sid in sids}
    no = {sid: len(analyze(data[sid])[1]) for sid in sids}
    mx = max(list(nm.values()) + list(no.values()) + [1]) + 1
    dx = Axis(0, mx, ox2 + 70, ox2 + pw)
    o.append(f'<text x="{ox2}" y="{oy - 14}" class="b">(d) Przerwy i przeniesienia na sensor</text>'
             f'<rect x="{ox2 + 250}" y="{oy - 24}" width="10" height="10" fill="#d62728"/><text x="{ox2 + 264}" y="{oy - 15}" class="a">przerwy</text>'
             f'<rect x="{ox2 + 320}" y="{oy - 24}" width="10" height="10" fill="#111"/><text x="{ox2 + 334}" y="{oy - 15}" class="a">przeniesienia</text>')
    for i, sid in enumerate(sids):
        y = oy + i * 34
        o.append(f'<text x="{ox2 + 62}" y="{y + 16}" class="a" text-anchor="end">Sensor {sid:03d}</text>'
                 f'<rect x="{dx(0)}" y="{y + 1}" width="{dx(no[sid]) - dx(0):.1f}" height="11" fill="#d62728"/>'
                 f'<text x="{dx(no[sid]) + 4:.1f}" y="{y + 10}" class="a">{no[sid]}</text>'
                 f'<rect x="{dx(0)}" y="{y + 14}" width="{dx(nm[sid]) - dx(0):.1f}" height="11" fill="#111"/>'
                 f'<text x="{dx(nm[sid]) + 4:.1f}" y="{y + 23}" class="a">{nm[sid]}</text>')
    write(path, W, H, o)


def write(path, w, h, body):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" style="max-width:{w}px;width:100%">{STYLE}'
                f'<rect width="100%" height="100%" fill="#fff"/>\n' + "\n".join(body) + "\n</svg>\n")


# --------------------------------------------------------------------------
def main(argv):
    dane = argv[0] if argv else "dane"
    out = argv[1] if len(argv) > 1 else "wizualizacje"
    data = {s: p for s, p in wl.load(os.path.join(dane, "pomiary.csv")).items()}
    events = read_events(os.path.join(dane, "zdarzenia.csv"))
    t_end = max(p[0] for pts in data.values() for p in pts)
    bands = node_downtimes(events, t_end)

    wl.main([os.path.join(dane, "pomiary.csv"), os.path.join(out, "1_liniowosc.svg")])
    timeline(data, bands, t_end, os.path.join(out, "2_os_czasu.svg"))
    stats_chart(data, events, bands, t_end, os.path.join(out, "3_statystyki.svg"))

    # ----- podsumowanie tekstowe (do README) -----
    L = ["WERYFIKACJA LINIOWOŚCI (R², nachylenie, start w dopuszczalnym przedziale)",
         f"{'sensor':>6} {'n':>5} {'a dop.':>10} {'a plik':>8} {'R²':>9} {'max |reszta|':>13} {'start OK':>9} {'przerwy':>8} {'przen.':>7} {'dostęp.':>8}"]
    for sid in sorted(data):
        pts = sorted(data[sid])
        a, b, r2 = wl.fit_line([p[0] for p in pts], [p[1] for p in pts])
        mr = max(abs(p[1] - (a * p[0] + b)) for p in pts)
        a0 = wl.declared_slope(sid)
        v = verify_start(sid, a, a * 1 + b)
        segs, outs, moves = analyze(pts)
        seqs = [p[0] for p in pts]
        av = len(seqs) / (max(seqs) - min(seqs) + 1) * 100
        L.append(f"{sid:>6} {len(pts):>5} {a:>10.5f} {a0 if a0 is not None else '-':>8} {r2:>9.6f} "
                 f"{mr:>13.5f} {('TAK' if v and v[0] else 'NIE') if v else '-':>9} {len(outs):>8} {len(moves):>7} {av:>7.1f}%")
    typ = Counter(e["typ"] for e in events)
    L += ["", "ZDARZENIA SIECI (zdarzenia.csv)"] + [f"  {k:<22} {v}" for k, v in sorted(typ.items())]
    with open(os.path.join(dane, "podsumowanie.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
