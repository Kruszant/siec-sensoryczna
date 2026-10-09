"""Powtarzalna symulacja do zebrania danych (bez interfejsu) + scenariusz zdarzeń.

Uruchamia zlew, węzły z nodes/ i sensory z sensors/ (stały seed => ten sam przebieg
parametrów), a w ustalonych chwilach symulacji wykonuje RĘCZNE operacje, tak jak
zrobiłby je użytkownik w pliku TXT / przez steruj.py:

    t =  80 s   wyłączenie węzła 2        (awaria węzła, sensory same szukają innego)
    t = 130 s   ponowne włączenie węzła 2
    t = 170 s   sensor 3 przeniesiony do węzła 1   (WEZEL=1)
    t = 200 s   sensor 3 znów w dowolnym węźle     (WEZEL=0)
    t = 220 s   sensor 5 ręcznie odłączony         (POLACZONY=0)
    t = 245 s   sensor 5 ponownie przyłączony      (POLACZONY=1)

Dodatkowo cały czas działają LOSOWE odłączenia sensorów (P_ODLACZENIA z plików
SENSORxxx.TXT) oraz próba dodania 5. węzła na początku (zlew ją odrzuca).

Wynik trafia do folderu dane/:  pomiary.csv  oraz  zdarzenia.csv.

Użycie: python symulacja.py [--czas 300] [--tick 0.2] [--wyjscie dane]
(czas podany w "sekundach symulacji"; tick skraca sekundę, 0.2 => 300 s trwa ok. 1 min)
"""
import argparse
import glob
import os
import time

import steruj
from node import Node, load_node_file
from sensor import Sensor, load_sensor_file
from sink import Sink


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--czas", type=float, default=300, help="czas symulacji [s symulacji]")
    p.add_argument("--tick", type=float, default=0.2, help="długość sekundy symulacji [s]")
    p.add_argument("--wyjscie", default="dane", help="folder na pliki CSV")
    a = p.parse_args()
    os.makedirs(a.wyjscie, exist_ok=True)
    quiet = lambda *_: None

    # stan wyjściowy plików sterujących (zapamiętujemy, żeby je przywrócić na końcu)
    node_files = sorted(glob.glob("nodes/NODE*.TXT"))
    sensor_files = sorted(glob.glob("sensors/SENSOR*.TXT"))
    for f in node_files:
        steruj.set_key(f, "AKTYWNY", 1)
    for f in sensor_files:
        steruj.set_key(f, "POLACZONY", 1)
        steruj.set_key(f, "WEZEL", 0)

    sink = Sink(csv_path=os.path.join(a.wyjscie, "pomiary.csv"),
                events_path=os.path.join(a.wyjscie, "zdarzenia.csv"), tick=a.tick).start()
    nodes = [Node(load_node_file(f)["ID"], log=quiet, path=f, tick=a.tick).start()
             for f in node_files]
    try:                                   # 5. węzeł - zlew go odrzuca (limit 4)
        Node(5, log=quiet).start()
    except ConnectionRefusedError:
        pass

    sensors = []
    for f in sensor_files:
        cfg = load_sensor_file(f)
        s = Sensor(cfg, tick=a.tick, log=quiet, path=f, seed=cfg["ID"])
        s.start()
        sensors.append(s)
        time.sleep(0.3 * a.tick)           # sensory pojawiają się po kolei

    node_f = lambda n: f"nodes/NODE{n:03d}.TXT"
    sens_f = lambda n: f"sensors/SENSOR{n:03d}.TXT"
    scenariusz = [                          # (t symulacji, opis, akcja)
        (80, "wyłączenie węzła 2", lambda: steruj.set_key(node_f(2), "AKTYWNY", 0)),
        (130, "włączenie węzła 2", lambda: steruj.set_key(node_f(2), "AKTYWNY", 1)),
        (170, "sensor 3 -> węzeł 1", lambda: steruj.set_key(sens_f(3), "WEZEL", 1)),
        (200, "sensor 3 -> dowolny węzeł", lambda: steruj.set_key(sens_f(3), "WEZEL", 0)),
        (220, "sensor 5 odłączony ręcznie", lambda: steruj.set_key(sens_f(5), "POLACZONY", 0)),
        (245, "sensor 5 przyłączony", lambda: steruj.set_key(sens_f(5), "POLACZONY", 1)),
    ]
    scenariusz = [x for x in scenariusz if x[0] < a.czas]

    t_start = time.time()
    try:
        while True:
            now = (time.time() - t_start) / a.tick
            if now >= a.czas:
                break
            while scenariusz and now >= scenariusz[0][0]:
                t, opis, akcja = scenariusz.pop(0)
                akcja()
                print(f"[t={now:5.1f}s] SCENARIUSZ: {opis}", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass

    for s in sensors:
        s.stop()
    for n in nodes:
        n.stop()
    sink.stop()
    for f in node_files:                    # przywrócenie stanu wyjściowego plików
        steruj.set_key(f, "AKTYWNY", 1)
    for f in sensor_files:
        steruj.set_key(f, "POLACZONY", 1)
        steruj.set_key(f, "WEZEL", 0)
    print(f"Gotowe: {a.wyjscie}/pomiary.csv ({len(sink.readings)} pomiarów), "
          f"{a.wyjscie}/zdarzenia.csv ({len(sink.events)} zdarzeń)")


if __name__ == "__main__":
    main()
