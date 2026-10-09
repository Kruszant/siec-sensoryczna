"""SENSOR TEMPERATURY o charakterystyce liniowej.

Parametry czytane są z pliku SENSORxxx.TXT (xxx = unikalny numer sensora).
Model:  T(k) = T_START + A * (X0 + k * DT)
  T_START - losowa wartość startowa z przedziału [T_START_MIN, T_START_MAX]
  A       - nachylenie prostej (°C na sekundę)
  X0      - losowe przesunięcie na charakterystyce [PRZESUNIECIE_MIN, PRZESUNIECIE_MAX]
  k       - numer kolejnego pomiaru, DT - okres próbkowania (1 s)

Sensor sam przyłącza się do sieci (auto-przyłączenie): pyta zlew o listę
aktywnych węzłów, wybiera węzeł i przedstawia się swoim numerem.

ODŁĄCZANIE RĘCZNE: sensor co sekundę czyta ponownie swój plik SENSORxxx.TXT.
  POLACZONY=0  -> sensor odłącza się od węzła (i czeka)
  POLACZONY=1  -> sensor przyłącza się ponownie
  WEZEL=N      -> sensor przechodzi do węzła N (przeniesienie), WEZEL=0 = dowolny
Zmiany można wpisać w Notatniku albo poleceniem:  python steruj.py 3 odlacz
Opcjonalnie P_ODLACZENIA > 0 włącza dodatkowo odłączanie w losowych chwilach.

Uruchomienie:  python sensor.py sensors/SENSOR001.TXT [--tick 1.0]
"""
import argparse
import os
import random
import re
import socket
import threading
import time

from common import HOST, SINK_PORT, LineReader, request, send_msg

DEFAULTS = {
    "TYP": "TEMPERATURA",
    "JEDNOSTKA": "C",
    "T_START_MIN": 15.0,
    "T_START_MAX": 25.0,
    "NACHYLENIE_A": 0.05,
    "PRZESUNIECIE_MIN": 0.0,
    "PRZESUNIECIE_MAX": 60.0,
    "SZUM": 0.0,
    "OKRES_PROBKOWANIA": 1.0,
    "POLACZONY": 1,          # 1 = przyłączony, 0 = ręcznie odłączony
    "WEZEL": 0,              # 0 = dowolny węzeł (auto), N = przyłącz/przenieś do węzła N
    "P_ODLACZENIA": 0.0,     # > 0 włącza dodatkowo losowe odłączanie
    "CZAS_ODLACZENIA_MIN": 3.0,
    "CZAS_ODLACZENIA_MAX": 8.0,
    "PRZENOSZENIE": 1,
}


def load_sensor_file(path: str) -> dict:
    """Czyta plik SENSORxxx.TXT w formacie KLUCZ=WARTOSC (# = komentarz)."""
    m = re.search(r"SENSOR(\d+)\.TXT$", os.path.basename(path), re.IGNORECASE)
    if not m:
        raise ValueError(f"Zła nazwa pliku sensora: {path} (oczekiwano SENSORxxx.TXT)")
    cfg = dict(DEFAULTS)
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line or "=" not in line:
                continue
            key, val = (x.strip() for x in line.split("=", 1))
            key = key.upper()
            if key in ("TYP", "JEDNOSTKA"):
                cfg[key] = val
            elif key in ("ID", "PRZENOSZENIE", "POLACZONY", "WEZEL"):
                cfg[key] = int(val)
            else:
                cfg[key] = float(val)
    file_id = int(m.group(1))
    cfg.setdefault("ID", file_id)
    if cfg["ID"] != file_id:
        raise ValueError(f"ID={cfg['ID']} w pliku nie zgadza się z nazwą {path}")
    return cfg


class LinearTemperatureModel:
    """Charakterystyka liniowa  T = T_START + A * (X0 + t)."""

    def __init__(self, cfg: dict, rng: random.Random):
        self.a = cfg["NACHYLENIE_A"]
        self.dt = cfg["OKRES_PROBKOWANIA"]
        self.noise = cfg["SZUM"]
        self.rng = rng
        self.t_start = rng.uniform(cfg["T_START_MIN"], cfg["T_START_MAX"])
        self.x0 = rng.uniform(cfg["PRZESUNIECIE_MIN"], cfg["PRZESUNIECIE_MAX"])
        self.k = 0

    def value_at(self, k: int) -> float:
        return self.t_start + self.a * (self.x0 + k * self.dt)

    def next(self) -> float:
        t = self.value_at(self.k)
        if self.noise:
            t += self.rng.gauss(0, self.noise)
        self.k += 1
        return round(t, 3)


class Sensor:
    def __init__(self, cfg: dict, tick: float = 1.0, sink_port: int = SINK_PORT,
                 seed=None, log=print, path: str = None):
        self.cfg = cfg
        self.id = cfg["ID"]
        self.path = path                    # plik SENSORxxx.TXT - czytany co sekundę
        self.tick = tick                    # długość "sekundy" (skrócona w testach)
        self.sink_port = sink_port
        self.rng = random.Random(seed)
        self.model = LinearTemperatureModel(cfg, self.rng)
        self.log = log
        self.node = None                    # nr węzła, do którego jest przyłączony
        self.history = []                   # historia przyłączeń (nr węzłów)
        self.pause_until = 0.0              # koniec losowej przerwy (tryb automatyczny)
        self.stop_event = threading.Event()

    # --- ręczne sterowanie przez plik ---------------------------------------
    def reload_control(self):
        """Ponownie czyta plik sensora i bierze z niego POLACZONY / WEZEL.

        Dzięki temu odłączanie i przenoszenie robi się RĘCZNIE: wystarczy
        zmienić wartość w SENSORxxx.TXT i zapisać plik (albo użyć steruj.py)."""
        if not self.path:
            return
        try:
            new = load_sensor_file(self.path)
        except (OSError, ValueError):
            return                          # plik w trakcie zapisu - zostaw stare
        for key in ("POLACZONY", "WEZEL", "P_ODLACZENIA",
                    "CZAS_ODLACZENIA_MIN", "CZAS_ODLACZENIA_MAX", "PRZENOSZENIE"):
            self.cfg[key] = new[key]

    # --- auto-przyłączenie -------------------------------------------------
    def discover_nodes(self):
        try:
            resp = request(self.sink_port, {"type": "get_nodes"})
            return resp.get("nodes", []) if resp else []
        except OSError:
            return []

    def choose_node(self, nodes):
        target = self.cfg["WEZEL"]
        if target:                          # ręcznie wskazany węzeł
            return next((n for n in nodes if n["node"] == target), None)
        if not nodes:
            return None
        candidates = nodes
        if self.cfg["PRZENOSZENIE"] and self.history and len(nodes) > 1:
            candidates = [n for n in nodes if n["node"] != self.history[-1]]
        return self.rng.choice(candidates)

    def try_connect(self):
        """Jedna próba przyłączenia. Zwraca gniazdo albo None."""
        n = self.choose_node(self.discover_nodes())
        if n is None:
            return None
        s = None
        try:
            s = socket.create_connection((HOST, n["port"]), timeout=2)
            s.settimeout(None)
            send_msg(s, {"type": "hello", "sensor": self.id,
                         "sensor_type": self.cfg["TYP"], "unit": self.cfg["JEDNOSTKA"]})
            resp = LineReader(s).read()
            if resp and resp.get("type") == "welcome":
                self.node = resp["node"]
                self.history.append(self.node)
                self.log(f"[SENSOR {self.id:03d}] przyłączony do węzła {self.node}")
                return s
            s.close()
        except OSError:
            if s:
                s.close()
        return None

    def disconnect(self, sock, why):
        self.log(f"[SENSOR {self.id:03d}] ODŁĄCZENIE od węzła {self.node} ({why})")
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()
        self.node = None

    # --- główna pętla (co 1 s) ---------------------------------------------
    def run(self):
        sock = None
        while not self.stop_event.is_set():
            t0 = time.monotonic()
            self.reload_control()
            want = self.cfg["POLACZONY"] == 1 and time.monotonic() >= self.pause_until
            target = self.cfg["WEZEL"]

            if sock and not want:
                self.disconnect(sock, "ręcznie: POLACZONY=0" if self.cfg["POLACZONY"] == 0
                                else "losowo")
                sock = None
            elif sock and target and target != self.node:
                self.disconnect(sock, f"ręcznie: przeniesienie do węzła {target}")
                sock = None

            if sock is None and want:
                sock = self.try_connect()

            # charakterystyka "biegnie" również w czasie odłączenia
            temp = self.model.next()
            if sock:
                try:
                    send_msg(sock, {"type": "reading", "sensor": self.id,
                                    "seq": self.model.k, "temp": temp,
                                    "unit": self.cfg["JEDNOSTKA"]})
                except OSError:             # węzeł zniknął - przy następnym kroku inny
                    sock.close()
                    sock, self.node = None, None

            # opcjonalny tryb automatyczny (P_ODLACZENIA > 0)
            if sock and self.rng.random() < self.cfg["P_ODLACZENIA"]:
                pause = self.rng.uniform(self.cfg["CZAS_ODLACZENIA_MIN"],
                                         self.cfg["CZAS_ODLACZENIA_MAX"])
                self.pause_until = time.monotonic() + pause * self.tick

            self.stop_event.wait(max(0.0, self.tick * self.cfg["OKRES_PROBKOWANIA"]
                                     - (time.monotonic() - t0)))
        if sock:
            sock.close()

    def start(self):
        th = threading.Thread(target=self.run, daemon=True)
        th.start()
        return th

    def stop(self):
        self.stop_event.set()


def main():
    p = argparse.ArgumentParser(description="Sensor temperatury (charakterystyka liniowa)")
    p.add_argument("plik", help="plik SENSORxxx.TXT")
    p.add_argument("--tick", type=float, default=1.0, help="długość sekundy symulacji")
    p.add_argument("--sink-port", type=int, default=SINK_PORT)
    a = p.parse_args()
    s = Sensor(load_sensor_file(a.plik), tick=a.tick, sink_port=a.sink_port,
               path=a.plik)
    try:
        s.run()
    except KeyboardInterrupt:
        s.stop()


if __name__ == "__main__":
    main()
