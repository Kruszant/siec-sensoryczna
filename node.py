"""WĘZEŁ sieci sensorycznej.

- ma unikalny numer (1..4), słucha na porcie 5000 + numer,
- przy starcie rejestruje się w zlewie (zlew przyjmuje max 4 węzły),
- w każdej chwili może przyjąć sensor (sensor sam się przyłącza),
- przekazuje do zlewu pomiary uzupełnione o swój numer,
- zgłasza zlewowi przyłączenie / odłączenie sensora (przenoszenie sensorów).

Węzeł może mieć własny plik NODExxx.TXT (folder nodes/), czytany co sekundę:
  AKTYWNY=0  -> węzeł wyłącza się (opuszcza sieć, sensory szukają innego węzła)
  AKTYWNY=1  -> węzeł włącza się ponownie (rejestruje się w zlewie)
Wyłączać można ręcznie w pliku albo poleceniem:  python steruj.py wezel 2 wylacz

Uruchomienie:  python node.py 1                    (bez pliku, zawsze aktywny)
               python node.py nodes/NODE001.TXT    (z plikiem - można wyłączać)
"""
import argparse
import os
import re
import socket
import socketserver
import threading
import time

from common import HOST, NODE_BASE_PORT, SINK_PORT, LineReader, send_msg


def load_node_file(path: str) -> dict:
    """Czyta plik NODExxx.TXT w formacie KLUCZ=WARTOSC (# = komentarz)."""
    m = re.search(r"NODE(\d+)\.TXT$", os.path.basename(path), re.IGNORECASE)
    if not m:
        raise ValueError(f"Zła nazwa pliku węzła: {path} (oczekiwano NODExxx.TXT)")
    cfg = {"AKTYWNY": 1}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if "=" not in line:
                continue
            key, val = (x.strip() for x in line.split("=", 1))
            if key.upper() in ("ID", "AKTYWNY"):
                cfg[key.upper()] = int(val)
    file_id = int(m.group(1))
    cfg.setdefault("ID", file_id)
    if cfg["ID"] != file_id:
        raise ValueError(f"ID={cfg['ID']} w pliku nie zgadza się z nazwą {path}")
    return cfg


class Node:
    def __init__(self, node_id: int, sink_port: int = SINK_PORT,
                 port: int = None, log=print, path: str = None, tick: float = 1.0):
        self.id = node_id
        self.path = path                    # plik NODExxx.TXT - czytany co sekundę
        self.tick = tick
        self.watcher = None
        self.serving = False
        self.stop_event = threading.Event()
        self.port = port if port is not None else NODE_BASE_PORT + node_id
        self.sink_port = sink_port
        self.log = log
        self.sensors = set()
        self.conns = set()
        self.lock = threading.Lock()
        self.sink = None
        self.server = None

    # --- komunikacja ze zlewem --------------------------------------------
    def register(self):
        self.sink = socket.create_connection((HOST, self.sink_port), timeout=3)
        send_msg(self.sink, {"type": "register_node", "node": self.id, "port": self.port})
        resp = LineReader(self.sink).read()
        if not resp or resp.get("type") != "ok":
            reason = resp.get("reason") if resp else "brak odpowiedzi"
            self.sink.close()
            self.sink = None
            raise ConnectionRefusedError(f"Zlew odrzucił węzeł {self.id}: {reason}")
        self.sink.settimeout(None)
        self.log(f"[WĘZEŁ {self.id}] zarejestrowany w zlewie, port {self.port}")

    def to_sink(self, msg: dict, sock: socket.socket = None):
        """Wysyła do zlewu; `sock` = połączenie z chwili przyłączenia sensora
        (po wyłączeniu i ponownym włączeniu węzła stare wiadomości nie trafią do nowego)."""
        msg["node"] = self.id
        with self.lock:
            try:
                send_msg(sock or self.sink, msg)
            except (OSError, AttributeError):
                self.log(f"[WĘZEŁ {self.id}] brak połączenia ze zlewem")

    # --- obsługa sensorów ---------------------------------------------------
    def handle_sensor(self, conn: socket.socket):
        self.conns.add(conn)
        reader = LineReader(conn)
        hello = reader.read()
        if not hello or hello.get("type") != "hello":
            return
        sid = hello["sensor"]
        sink = self.sink
        send_msg(conn, {"type": "welcome", "node": self.id})
        with self.lock:
            self.sensors.add(sid)
        self.log(f"[WĘZEŁ {self.id}] przyłączono sensor {sid:03d}")
        self.to_sink({"type": "sensor_attached", "sensor": sid}, sink)
        try:
            while True:
                msg = reader.read()
                if msg is None:
                    break
                if msg.get("type") == "reading":
                    self.to_sink({"type": "data", "sensor": sid, "seq": msg["seq"],
                                  "temp": msg["temp"], "unit": msg.get("unit", "C"),
                                  "ts": time.time()}, sink)
        finally:
            self.conns.discard(conn)
            with self.lock:
                self.sensors.discard(sid)
            self.log(f"[WĘZEŁ {self.id}] sensor {sid:03d} odłączony")
            self.to_sink({"type": "sensor_detached", "sensor": sid}, sink)

    # --- włączanie / wyłączanie ---------------------------------------------
    @property
    def active(self) -> bool:
        return self.server is not None

    def activate(self):
        """Uruchamia serwer i rejestruje węzeł w zlewie (ConnectionRefusedError = odmowa)."""
        node = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                node.handle_sensor(self.request)

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        server = Server((HOST, self.port), Handler)
        self.server = server
        try:
            self.register()
        except Exception:
            self.deactivate()
            raise
        self.serving = True
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def deactivate(self):
        """Węzeł opuszcza sieć: zrywa połączenia z sensorami i ze zlewem."""
        server, self.server = self.server, None
        if server:
            if self.serving:                 # serve_forever działa dopiero po register()
                server.shutdown()
                self.serving = False
            server.server_close()
        for c in list(self.conns):           # zrywamy połączenia z sensorami
            try:
                c.shutdown(socket.SHUT_RDWR)
                c.close()
            except OSError:
                pass
        if self.sink:
            self.sink.close()
            self.sink = None

    def sync_with_file(self):
        """Dopasowuje stan węzła do AKTYWNY w pliku NODExxx.TXT."""
        try:
            want = load_node_file(self.path)["AKTYWNY"] == 1
        except (OSError, ValueError):
            return                           # plik w trakcie zapisu - zostaw stan
        if want and not self.active:
            try:
                self.activate()
            except (OSError, ConnectionRefusedError) as e:
                self.log(f"[WĘZEŁ {self.id}] nie można włączyć: {e}")
        elif not want and self.active:
            self.deactivate()
            self.log(f"[WĘZEŁ {self.id}] WYŁĄCZONY (AKTYWNY=0)")

    def watch(self):
        while not self.stop_event.wait(self.tick):
            self.sync_with_file()

    def start(self):
        if not self.path:
            self.activate()                  # bez pliku: odmowa zlewu = wyjątek
            return self
        self.sync_with_file()
        self.watcher = threading.Thread(target=self.watch, daemon=True)
        self.watcher.start()
        return self

    def stop(self):
        self.stop_event.set()
        self.deactivate()


def main():
    p = argparse.ArgumentParser(description="Węzeł sieci sensorycznej")
    p.add_argument("nr", help="numer węzła (1..4) albo plik nodes/NODExxx.TXT")
    p.add_argument("--sink-port", type=int, default=SINK_PORT)
    a = p.parse_args()
    if a.nr.isdigit():
        n = Node(int(a.nr), sink_port=a.sink_port)
    else:
        n = Node(load_node_file(a.nr)["ID"], sink_port=a.sink_port, path=a.nr)
    n.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        n.stop()


if __name__ == "__main__":
    main()
