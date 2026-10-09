"""Ręczne sterowanie sensorem - zmienia POLACZONY / WEZEL w pliku SENSORxxx.TXT.

Działający sensor czyta swój plik co sekundę, więc zmiana działa od razu.

  python steruj.py 3 odlacz         -> sensor 003 odłącza się od węzła
  python steruj.py 3 przylacz       -> sensor 003 przyłącza się ponownie
  python steruj.py 3 przenies 2     -> sensor 003 przechodzi do węzła 2
  python steruj.py 3 auto           -> sensor 003 może być w dowolnym węźle
  python steruj.py 3 stan           -> pokazuje aktualne ustawienia

Węzły (pliki nodes/NODExxx.TXT, klucz AKTYWNY):
  python steruj.py wezel 2 wylacz   -> węzeł 2 opuszcza sieć (AKTYWNY=0)
  python steruj.py wezel 2 wlacz    -> węzeł 2 wraca do sieci (AKTYWNY=1)
  python steruj.py wezel 2 stan     -> pokazuje ustawienia węzła
"""
import os
import re
import sys

FOLDER = "sensors"
NODE_FOLDER = "nodes"


def set_key(path, key, value):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    pattern = rf"^({key}\s*=\s*)[^\s#]*"
    if re.search(pattern, text, flags=re.M):
        text = re.sub(pattern, rf"\g<1>{value}", text, count=1, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\n{key}={value}\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def get_key(path, key, default="?"):
    with open(path, encoding="utf-8") as f:
        m = re.search(rf"^{key}\s*=\s*([^\s#]*)", f.read(), flags=re.M)
    return m.group(1) if m else default


def steruj_wezel(argv):
    if len(argv) < 2 or not argv[0].isdigit():
        print(__doc__)
        return 1
    nid, cmd = int(argv[0]), argv[1].lower()
    path = os.path.join(NODE_FOLDER, f"NODE{nid:03d}.TXT")
    if not os.path.exists(path):
        print(f"Brak pliku {path}")
        return 1
    if cmd == "wylacz":
        set_key(path, "AKTYWNY", 0)
        print(f"Węzeł {nid:03d}: WYŁĄCZ (AKTYWNY=0)")
    elif cmd == "wlacz":
        set_key(path, "AKTYWNY", 1)
        print(f"Węzeł {nid:03d}: WŁĄCZ (AKTYWNY=1)")
    elif cmd != "stan":
        print(__doc__)
        return 1
    print(f"  {path}: AKTYWNY={get_key(path, 'AKTYWNY', '1')}")
    return 0


def main(argv):
    if argv and argv[0].lower() in ("wezel", "node"):
        return steruj_wezel(argv[1:])
    if len(argv) < 2:
        print(__doc__)
        return 1
    sid, cmd = int(argv[0]), argv[1].lower()
    path = os.path.join(FOLDER, f"SENSOR{sid:03d}.TXT")
    if not os.path.exists(path):
        print(f"Brak pliku {path}")
        return 1

    if cmd == "odlacz":
        set_key(path, "POLACZONY", 0)
        print(f"Sensor {sid:03d}: ODŁĄCZ (POLACZONY=0)")
    elif cmd == "przylacz":
        set_key(path, "POLACZONY", 1)
        print(f"Sensor {sid:03d}: PRZYŁĄCZ (POLACZONY=1)")
    elif cmd == "przenies":
        if len(argv) < 3 or not argv[2].isdigit() or not 1 <= int(argv[2]) <= 4:
            print("Podaj numer węzła 1..4, np.: python steruj.py 3 przenies 2")
            return 1
        set_key(path, "WEZEL", int(argv[2]))
        set_key(path, "POLACZONY", 1)
        print(f"Sensor {sid:03d}: PRZENIEŚ do węzła {argv[2]} (WEZEL={argv[2]})")
    elif cmd == "auto":
        set_key(path, "WEZEL", 0)
        print(f"Sensor {sid:03d}: dowolny węzeł (WEZEL=0)")
    elif cmd == "stan":
        pass
    else:
        print(__doc__)
        return 1
    print(f"  {path}: POLACZONY={get_key(path, 'POLACZONY', '1')}  "
          f"WEZEL={get_key(path, 'WEZEL', '0')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
