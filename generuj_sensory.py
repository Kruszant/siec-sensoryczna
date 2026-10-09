"""Tworzy pliki SENSORxxx.TXT z losowymi parametrami.

Użycie: python generuj_sensory.py 6        -> sensors/SENSOR001.TXT ... SENSOR006.TXT
                                              + nodes/NODE001.TXT ... NODE004.TXT
"""
import os
import random
import sys

TEMPLATE = """# Plik konfiguracyjny sensora nr {id:03d}
ID={id:03d}
TYP=TEMPERATURA
JEDNOSTKA=C
# charakterystyka liniowa: T = T_START + A * (X0 + t)
T_START_MIN={tmin}        # losowa wartość startowa z przedziału
T_START_MAX={tmax}
NACHYLENIE_A={a}       # współczynnik kierunkowy prostej [°C/s]
PRZESUNIECIE_MIN=0        # losowe przesunięcie X0 na charakterystyce [s]
PRZESUNIECIE_MAX={xmax}
SZUM=0.0                  # opcjonalny szum gaussowski (0 = czysta prosta)
OKRES_PROBKOWANIA=1.0     # pomiar co 1 s
# --- STEROWANIE RĘCZNE (sensor czyta ten plik co sekundę) ---
POLACZONY=1               # 1 = przyłączony, 0 = odłącz sensor od węzła
WEZEL=0                   # 0 = dowolny węzeł, 1..4 = przyłącz / przenieś do tego węzła
# --- opcjonalne odłączanie w losowych chwilach (0 = wyłączone) ---
P_ODLACZENIA=0            # prawdopodobieństwo odłączenia w każdej sekundzie
CZAS_ODLACZENIA_MIN=3     # [s]
CZAS_ODLACZENIA_MAX=8     # [s]
PRZENOSZENIE=1            # 1 = po odłączeniu przyłącz do innego węzła
"""


NODE_TEMPLATE = """# Plik konfiguracyjny węzła nr {id:03d} (czytany co sekundę)
ID={id:03d}
AKTYWNY=1                 # 1 = węzeł działa, 0 = węzeł wyłączony (opuszcza sieć)
"""


def generate_nodes(n: int = 4, folder: str = "nodes"):
    os.makedirs(folder, exist_ok=True)
    paths = []
    for i in range(1, n + 1):
        path = os.path.join(folder, f"NODE{i:03d}.TXT")
        with open(path, "w", encoding="utf-8") as f:
            f.write(NODE_TEMPLATE.format(id=i))
        paths.append(path)
    return paths


def generate(n: int, folder: str = "sensors", seed=None):
    rng = random.Random(seed)
    os.makedirs(folder, exist_ok=True)
    paths = []
    for i in range(1, n + 1):
        tmin = rng.randint(-10, 30)
        path = os.path.join(folder, f"SENSOR{i:03d}.TXT")
        with open(path, "w", encoding="utf-8") as f:
            f.write(TEMPLATE.format(id=i, tmin=tmin, tmax=tmin + 5,
                                    a=round(rng.choice([-1, 1]) * rng.uniform(0.02, 0.2), 3),
                                    xmax=rng.randint(10, 100)))
        paths.append(path)
    return paths


if __name__ == "__main__":
    for p in generate_nodes() + generate(int(sys.argv[1]) if len(sys.argv) > 1 else 6):
        print("utworzono", p)
