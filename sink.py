"""ZLEW (SINK) sieci sensorycznej z aplikacją wyświetlającą dane.

- przyjmuje rejestrację węzłów (maksymalnie 4; piąty jest odrzucany),
- udostępnia sensorom listę aktywnych węzłów (auto-przyłączenie),
- odbiera pomiary i pokazuje: NR WĘZŁA, NR SENSORA, PRZESŁANY WYNIK,
- śledzi przenoszenie sensorów między węzłami oraz ich odłączenia,
- zapisuje wszystkie pomiary do pliku CSV (pomiary.csv),
- zapisuje zdarzenia sieci (przyłączenia, odłączenia, przeniesienia, awarie
  węzłów) do drugiego pliku CSV (zdarzenia.csv) - dane do wizualizacji.

Uruchomienie:  python sink.py            (odświeżany widok w terminalu)
               python sink.py --no-ui    (tylko log zdarzeń)
"""
import argparse
import csv
import socketserver
import threading
import time
from datetime import datetime

from common import HOST, MAX_NODES, SINK_PORT, LineReader, send_msg


class Sink:
    def __init__(self, port: int = SINK_PORT, max_nodes: int = MAX_NODES,
                 csv_path: str = None, log=None, events_path: str = None,
                 tick: float = 1.0):
        self.port = port
        self.tick = tick              # długość "sekundy" symulacji (do kolumny t_sym)
        self.t0 = time.time()         # początek symulacji
        self.events_path = events_path
        self.max_nodes = max_nodes
        self.nodes = {}       # nr węzła -> {"port": .., "since": ..}
        self.sensors = {}     # nr sensora -> stan ostatniego pomiaru
        self.readings = []    # (ts, węzeł, sensor, seq, temp)
        self.events = []      # log zdarzeń (do wyświetlania)
        self.lock = threading.Lock()
        self.csv_path = csv_path
        self.log_fn = log
        self.server = None
        if csv_path:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["czas", "wezel", "sensor", "seq", "temperatura", "t_sym"])
        if events_path:
            with open(events_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["czas", "t_sym", "typ", "wezel", "sensor", "opis"])

    def t_sym(self, ts: float = None) -> float:
        """Czas symulacji w "sekundach" (niezależny od skrócenia tick)."""
        return round(((ts or time.time()) - self.t0) / self.tick, 2)

    def event(self, text: str, kind: str = "info", node=None, sensor=None):
        """Dopisuje zdarzenie do widoku, do pliku zdarzenia.csv i do logu.

        kind: wezel_dolaczyl | wezel_opuscil | wezel_odrzucony | sensor_przylaczony |
              sensor_odlaczony | sensor_przeniesiony"""
        line = f"{datetime.now():%H:%M:%S}  {text}"
        if self.events_path:
            with self.lock, open(self.events_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([f"{datetime.now():%H:%M:%S}", self.t_sym(), kind,
                                        node, sensor, text])
        with self.lock:
            self.events.append(line)
            self.events = self.events[-200:]
        if self.log_fn:
            self.log_fn(line)

    # --- obsługa połączeń ---------------------------------------------------
    def handle(self, conn):
        reader = LineReader(conn)
        first = reader.read()
        if not first:
            return
        if first["type"] == "get_nodes":
            with self.lock:
                nodes = [{"node": n, "port": d["port"],
                          "sensors": sum(1 for s in self.sensors.values()
                                         if s["online"] and s["node"] == n)}
                         for n, d in sorted(self.nodes.items())]
            send_msg(conn, {"type": "nodes", "nodes": nodes})
        elif first["type"] == "register_node":
            self.handle_node(conn, reader, first)

    def handle_node(self, conn, reader, reg):
        nid = reg["node"]
        with self.lock:
            if nid in self.nodes:
                reason = f"węzeł {nid} już istnieje"
            elif len(self.nodes) >= self.max_nodes:
                reason = f"osiągnięto limit {self.max_nodes} węzłów"
            else:
                reason = None
                self.nodes[nid] = {"port": reg["port"], "since": time.time()}
        if reason:
            send_msg(conn, {"type": "error", "reason": reason})
            self.event(f"ODRZUCONO węzeł {nid}: {reason}", "wezel_odrzucony", nid)
            return
        send_msg(conn, {"type": "ok"})
        self.event(f"Węzeł {nid} dołączył do sieci (port {reg['port']})", "wezel_dolaczyl", nid)
        try:
            while True:
                msg = reader.read()
                if msg is None:
                    break
                self.on_node_msg(nid, msg)
        finally:
            with self.lock:
                self.nodes.pop(nid, None)
                for s in self.sensors.values():
                    if s["node"] == nid:
                        s["online"] = False
            self.event(f"Węzeł {nid} opuścił sieć", "wezel_opuscil", nid)

    def on_node_msg(self, nid, msg):
        t = msg["type"]
        sid = msg.get("sensor")
        if t == "sensor_attached":
            with self.lock:
                st = self.sensors.setdefault(sid, {"temp": None, "seq": None, "ts": None,
                                                   "moves": 0, "count": 0, "node": None})
                prev_node = st["node"]
                moved = prev_node is not None and prev_node != nid
                if moved:
                    st["moves"] += 1
                st.update(node=nid, online=True)
            if moved:
                self.event(f"Sensor {sid:03d} PRZENIESIONY: węzeł {prev_node} -> {nid}",
                           "sensor_przeniesiony", nid, sid)
            else:
                self.event(f"Sensor {sid:03d} przyłączony do węzła {nid}", "sensor_przylaczony", nid, sid)
        elif t == "sensor_detached":
            with self.lock:
                if sid in self.sensors and self.sensors[sid]["node"] == nid:
                    self.sensors[sid]["online"] = False
            self.event(f"Sensor {sid:03d} odłączony od węzła {nid}", "sensor_odlaczony", nid, sid)
        elif t == "data":
            with self.lock:
                st = self.sensors.setdefault(sid, {"moves": 0, "count": 0})
                st.update(node=nid, online=True, temp=msg["temp"], seq=msg["seq"],
                          ts=msg["ts"], unit=msg.get("unit", "C"))
                st["count"] += 1
                self.readings.append((msg["ts"], nid, sid, msg["seq"], msg["temp"]))
            if self.csv_path:
                with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow([f"{datetime.fromtimestamp(msg['ts']):%H:%M:%S}",
                                            nid, sid, msg["seq"], msg["temp"],
                                            self.t_sym(msg["ts"])])

    # --- widok aplikacji ----------------------------------------------------
    def render(self) -> str:
        with self.lock:
            nodes = dict(self.nodes)
            sensors = {k: dict(v) for k, v in self.sensors.items()}
            events = list(self.events[-8:])
        out = []
        out.append("=" * 72)
        out.append(f" ZLEW (SINK) - SIEĆ SENSORYCZNA          {datetime.now():%Y-%m-%d %H:%M:%S}")
        out.append("=" * 72)
        out.append(f" Węzły w sieci: {len(nodes)}/{self.max_nodes}   "
                   + "  ".join(f"[W{n}: {sum(1 for s in sensors.values() if s.get('online') and s.get('node') == n)} sens.]"
                               for n in sorted(nodes)))
        out.append("-" * 72)
        out.append(f" {'WĘZEŁ':^7}| {'SENSOR':^8}| {'TEMPERATURA':^13}| {'NR POM.':^8}| "
                   f"{'CZAS':^9}| {'STATUS':^9}| PRZEN.")
        out.append("-" * 72)
        for sid in sorted(sensors):
            s = sensors[sid]
            temp = f"{s['temp']:8.2f} °{s.get('unit', 'C')}" if s.get("temp") is not None else "   ---"
            ts = f"{datetime.fromtimestamp(s['ts']):%H:%M:%S}" if s.get("ts") else "--:--:--"
            status = "ONLINE" if s.get("online") else "ODŁĄCZ."
            out.append(f" {('W' + str(s.get('node'))):^7}| {f'{sid:03d}':^8}| {temp:^13}| "
                       f"{str(s.get('seq')):^8}| {ts:^9}| {status:^9}| {s['moves']:^5}")
        if not sensors:
            out.append(" (brak sensorów)")
        out.append("-" * 72)
        out.append(" Ostatnie zdarzenia:")
        out.extend("   " + e for e in events)
        out.append("=" * 72)
        return "\n".join(out)

    # --- start / stop -------------------------------------------------------
    def start(self):
        sink = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                sink.handle(self.request)

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server((HOST, self.port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()


def main():
    p = argparse.ArgumentParser(description="Zlew sieci sensorycznej")
    p.add_argument("--port", type=int, default=SINK_PORT)
    p.add_argument("--csv", default="pomiary.csv")
    p.add_argument("--zdarzenia", default="zdarzenia.csv", help="plik CSV ze zdarzeniami")
    p.add_argument("--no-ui", action="store_true", help="bez odświeżanego widoku")
    a = p.parse_args()
    sink = Sink(a.port, csv_path=a.csv, events_path=a.zdarzenia,
                log=print if a.no_ui else None).start()
    print(f"Zlew nasłuchuje na porcie {a.port}")
    try:
        while True:
            time.sleep(1)
            if not a.no_ui:
                print("\033[2J\033[H" + sink.render(), flush=True)
    except KeyboardInterrupt:
        sink.stop()


if __name__ == "__main__":
    main()
