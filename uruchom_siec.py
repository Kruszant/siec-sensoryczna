"""Uruchamia całą sieć w jednym oknie: zlew + 4 węzły + sensory z folderu sensors/.

Odłączanie i przenoszenie sensorów robi się RĘCZNIE z drugiego okna terminala:
    python steruj.py 3 odlacz        python steruj.py 3 przylacz
    python steruj.py 3 przenies 2    python steruj.py 3 auto
(albo edytując POLACZONY / WEZEL w pliku SENSORxxx.TXT w Notatniku).
Węzły też mają pliki (nodes/NODExxx.TXT) i można je wyłączać:
    python steruj.py wezel 2 wylacz  /  python steruj.py wezel 2 wlacz
Próba dodania 5. węzła pokazuje działanie limitu 4 węzłów.

Użycie: python uruchom_siec.py [--czas 60] [--tick 1.0]
"""
import argparse
import glob
import time

from node import Node, load_node_file
from sensor import Sensor, load_sensor_file
from sink import Sink


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--czas", type=float, default=600, help="czas symulacji [s]")
    p.add_argument("--tick", type=float, default=1.0)
    p.add_argument("--folder", default="sensors")
    p.add_argument("--wezly", default="nodes", help="folder z plikami NODExxx.TXT")
    a = p.parse_args()

    quiet = lambda *_: None
    sink = Sink(csv_path="pomiary.csv").start()
    nodes = []
    for path in sorted(glob.glob(f"{a.wezly}/NODE*.TXT")):
        nodes.append(Node(load_node_file(path)["ID"], log=quiet, path=path,
                          tick=a.tick).start())

    try:                                   # 5. węzeł - zlew go odrzuci
        Node(5, log=quiet).start()
    except ConnectionRefusedError:
        pass

    sensors = []
    for path in sorted(glob.glob(f"{a.folder}/SENSOR*.TXT")):
        s = Sensor(load_sensor_file(path), tick=a.tick, log=quiet, path=path)
        s.start()
        sensors.append(s)
        time.sleep(0.3 * a.tick)           # sensory pojawiają się po kolei

    start = time.time()
    try:
        while time.time() - start < a.czas * a.tick:
            time.sleep(a.tick)
            print("\033[2J\033[H" + sink.render(), flush=True)
    except KeyboardInterrupt:
        pass
    for s in sensors:
        s.stop()
    for n in nodes:
        n.stop()
    sink.stop()
    print("Zakończono. Pomiary zapisano w pomiary.csv")


if __name__ == "__main__":
    main()
