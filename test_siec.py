"""Testy sieci sensorycznej.  Uruchomienie:  python -m unittest -v test_siec"""
import os
import random
import re
import tempfile
import time
import unittest

from node import Node, load_node_file
from sensor import LinearTemperatureModel, Sensor, load_sensor_file
from sink import Sink

TICK = 0.05          # skrócona "sekunda" -> testy trwają kilka sekund
_port = [6100]


def next_ports():
    """Każdy test dostaje własną pulę portów (zlew + 4 węzły)."""
    _port[0] += 10
    return _port[0]


def make_sensor_file(folder, sid, **over):
    params = dict(T_START_MIN=20, T_START_MAX=22, NACHYLENIE_A=0.5,
                  PRZESUNIECIE_MIN=0, PRZESUNIECIE_MAX=10, P_ODLACZENIA=0,
                  CZAS_ODLACZENIA_MIN=2, CZAS_ODLACZENIA_MAX=3, PRZENOSZENIE=1)
    params.update(over)
    path = os.path.join(folder, f"SENSOR{sid:03d}.TXT")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"ID={sid:03d}\n")
        for k, v in params.items():
            f.write(f"{k}={v}   # komentarz\n")
    return path


def wait_until(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class TestPlikSensora(unittest.TestCase):
    def test_wczytanie_parametrow(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = load_sensor_file(make_sensor_file(d, 7, NACHYLENIE_A=0.25))
            self.assertEqual(cfg["ID"], 7)
            self.assertEqual(cfg["NACHYLENIE_A"], 0.25)
            self.assertEqual(cfg["TYP"], "TEMPERATURA")

    def test_zla_nazwa_pliku(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "czujnik.txt")
            open(path, "w").close()
            with self.assertRaises(ValueError):
                load_sensor_file(path)

    def test_niezgodny_numer(self):
        with tempfile.TemporaryDirectory() as d:
            path = make_sensor_file(d, 3)
            os.rename(path, os.path.join(d, "SENSOR004.TXT"))
            with self.assertRaises(ValueError):
                load_sensor_file(os.path.join(d, "SENSOR004.TXT"))


class TestCharakterystykaLiniowa(unittest.TestCase):
    def setUp(self):
        self.cfg = {"T_START_MIN": 10, "T_START_MAX": 30, "NACHYLENIE_A": 0.3,
                    "PRZESUNIECIE_MIN": 5, "PRZESUNIECIE_MAX": 50,
                    "SZUM": 0.0, "OKRES_PROBKOWANIA": 1.0}

    def test_start_losowy_w_przedziale(self):
        starts = set()
        for seed in range(20):
            m = LinearTemperatureModel(self.cfg, random.Random(seed))
            self.assertTrue(10 <= m.t_start <= 30)
            self.assertTrue(5 <= m.x0 <= 50)
            starts.add(round(m.t_start, 3))
        self.assertGreater(len(starts), 10)   # wartości naprawdę losowe

    def test_kolejne_wartosci_na_prostej(self):
        m = LinearTemperatureModel(self.cfg, random.Random(1))
        vals = [m.next() for _ in range(20)]
        self.assertAlmostEqual(vals[0], m.t_start + 0.3 * m.x0, places=2)
        diffs = [round(b - a, 3) for a, b in zip(vals, vals[1:])]
        self.assertTrue(all(abs(d - 0.3) < 0.002 for d in diffs))   # stały przyrost = A


class TestWeryfikacjaLiniowosci(unittest.TestCase):
    """Sprawdza, że narzędzie do weryfikacji (regresja) rozróżnia prostą od danych z szumem."""

    def serie(self, szum, n=300):
        cfg = {"T_START_MIN": 10, "T_START_MAX": 20, "NACHYLENIE_A": 0.1,
               "PRZESUNIECIE_MIN": 0, "PRZESUNIECIE_MAX": 30, "SZUM": szum,
               "OKRES_PROBKOWANIA": 1.0}
        m = LinearTemperatureModel(cfg, random.Random(5))
        ys = [m.next() for _ in range(n)]
        return list(range(1, n + 1)), ys

    def test_czysta_prosta_ma_r2_rowne_1(self):
        from wykres_liniowosci import fit_line
        xs, ys = self.serie(0.0)
        a, b, r2 = fit_line(xs, ys)
        self.assertAlmostEqual(a, 0.1, places=6)
        self.assertGreater(r2, 0.999999)
        self.assertLess(max(abs(y - (a * x + b)) for x, y in zip(xs, ys)), 1e-6)

    def test_szum_jest_wykrywany(self):
        from wykres_liniowosci import fit_line
        xs, ys = self.serie(0.3)
        a, b, r2 = fit_line(xs, ys)
        res = [y - (a * x + b) for x, y in zip(xs, ys)]
        std = (sum(r * r for r in res) / len(res)) ** 0.5
        self.assertLess(r2, 0.9999)                 # R² wyraźnie poniżej 1
        self.assertAlmostEqual(std, 0.3, delta=0.06)  # odchylenie reszt ~ SZUM
        self.assertAlmostEqual(a, 0.1, delta=0.005)   # nachylenie nadal odtworzone


class TestSiec(unittest.TestCase):
    def setUp(self):
        self.base = next_ports()
        self.tmp = tempfile.TemporaryDirectory()
        self.sink = Sink(port=self.base).start()
        self.nodes, self.sensors = [], []

    def tearDown(self):
        for s in self.sensors:
            s.stop()
        time.sleep(3 * TICK)
        for n in self.nodes:
            n.stop()
        self.sink.stop()
        self.tmp.cleanup()

    def add_node(self, nid):
        n = Node(nid, sink_port=self.base, port=self.base + nid, log=lambda *_: None).start()
        self.nodes.append(n)
        return n

    def add_sensor(self, sid, seed=None, **over):
        path = make_sensor_file(self.tmp.name, sid, **over)
        s = Sensor(load_sensor_file(path), tick=TICK, sink_port=self.base, seed=seed,
                   log=lambda *_: None, path=path)
        s.file = path
        s.start()
        self.sensors.append(s)
        return s

    def test_max_4_wezly(self):
        for i in range(1, 5):
            self.add_node(i)
        self.assertEqual(len(self.sink.nodes), 4)
        with self.assertRaises(ConnectionRefusedError):
            Node(5, sink_port=self.base, port=self.base + 5, log=lambda *_: None).start()
        self.assertEqual(len(self.sink.nodes), 4)

    def test_duplikat_numeru_wezla(self):
        self.add_node(1)
        with self.assertRaises(ConnectionRefusedError):
            Node(1, sink_port=self.base, port=self.base + 6, log=lambda *_: None).start()

    def test_auto_przylaczenie_i_dane_w_zlewie(self):
        self.add_node(1)
        self.add_node(2)
        s = self.add_sensor(11)
        self.assertTrue(wait_until(lambda: self.sink.sensors.get(11, {}).get("count", 0) >= 5))
        st = self.sink.sensors[11]
        self.assertIn(st["node"], (1, 2))                 # identyfikacja węzła
        self.assertEqual(st["node"], s.node)
        # wyniki dotarły w kolejności i leżą na prostej o nachyleniu A=0.5
        temps = [r[4] for r in self.sink.readings if r[2] == 11][:5]
        for a, b in zip(temps, temps[1:]):
            self.assertAlmostEqual(b - a, 0.5, places=2)
        view = self.sink.render()
        self.assertIn("011", view)
        self.assertIn("ONLINE", view)

    def test_przylaczenie_gdy_wezel_pojawi_sie_pozniej(self):
        s = self.add_sensor(12)
        time.sleep(5 * TICK)
        self.assertIsNone(s.node)                          # brak węzłów - czeka
        self.add_node(3)
        self.assertTrue(wait_until(lambda: s.node == 3))
        self.assertTrue(wait_until(lambda: self.sink.sensors.get(12, {}).get("count", 0) > 0))

    def test_odlaczanie_i_przenoszenie_miedzy_wezlami(self):
        for i in range(1, 5):
            self.add_node(i)
        s = self.add_sensor(13, seed=3, P_ODLACZENIA=0.5,
                            CZAS_ODLACZENIA_MIN=1, CZAS_ODLACZENIA_MAX=2)
        self.assertTrue(wait_until(lambda: len(s.history) >= 4, timeout=10))
        # PRZENOSZENIE=1: kolejne przyłączenia zawsze do innego węzła
        for a, b in zip(s.history, s.history[1:]):
            self.assertNotEqual(a, b)
        self.assertGreaterEqual(self.sink.sensors[13]["moves"], 3)
        moves = [re.search(r"węzeł (\d) -> (\d)", e) for e in self.sink.events
                 if "PRZENIESIONY" in e]
        self.assertTrue(moves)
        self.assertTrue(all(m.group(1) != m.group(2) for m in moves))
        self.assertTrue(any("odłączony" in e for e in self.sink.events))

    # ---------- ręczne sterowanie (plik SENSORxxx.TXT / steruj.py) ----------
    def edit(self, s, **kv):
        import steruj
        for k, v in kv.items():
            steruj.set_key(s.file, k, v)

    def test_reczne_odlaczenie_i_przylaczenie(self):
        self.add_node(1)
        self.add_node(2)
        s = self.add_sensor(21)
        self.assertTrue(wait_until(lambda: self.sink.sensors.get(21, {}).get("online")))
        self.edit(s, POLACZONY=0)                          # ręczne odłączenie
        self.assertTrue(wait_until(lambda: not self.sink.sensors[21]["online"]))
        self.assertIsNone(s.node)
        count = self.sink.sensors[21]["count"]
        time.sleep(6 * TICK)
        self.assertEqual(self.sink.sensors[21]["count"], count)   # brak danych
        self.assertFalse(self.sink.sensors[21]["online"])          # i zostaje odłączony
        self.edit(s, POLACZONY=1)                          # ręczne przyłączenie
        self.assertTrue(wait_until(lambda: self.sink.sensors[21]["online"]
                                   and self.sink.sensors[21]["count"] > count))
        # charakterystyka biegła dalej - nadal ta sama prosta
        temps = {r[3]: r[4] for r in self.sink.readings if r[2] == 21}
        k1, k2 = min(temps), max(temps)
        self.assertAlmostEqual((temps[k2] - temps[k1]) / (k2 - k1), 0.5, places=2)

    def test_reczne_przeniesienie_do_wezla(self):
        for i in range(1, 5):
            self.add_node(i)
        s = self.add_sensor(22, WEZEL=1)                   # startuje na węźle 1
        self.assertTrue(wait_until(lambda: self.sink.sensors.get(22, {}).get("node") == 1))
        for target in (3, 2, 4):
            self.edit(s, WEZEL=target)
            self.assertTrue(wait_until(lambda: self.sink.sensors[22]["node"] == target
                                       and self.sink.sensors[22]["online"]))
        self.assertEqual(s.history, [1, 3, 2, 4])
        self.assertEqual(self.sink.sensors[22]["moves"], 3)
        self.assertTrue(any("PRZENIESIONY: węzeł 1 -> 3" in e for e in self.sink.events))

    def test_steruj_cli(self):
        import steruj
        path = make_sensor_file(self.tmp.name, 23)
        cfg = load_sensor_file(path)
        self.assertEqual((cfg["POLACZONY"], cfg["WEZEL"]), (1, 0))
        steruj.set_key(path, "POLACZONY", 0)
        steruj.set_key(path, "WEZEL", 4)
        cfg = load_sensor_file(path)
        self.assertEqual((cfg["POLACZONY"], cfg["WEZEL"]), (0, 4))

    def test_wiele_sensorow_na_wielu_wezlach(self):
        for i in range(1, 5):
            self.add_node(i)
        for sid in range(1, 9):
            self.add_sensor(sid, seed=sid)
        self.assertTrue(wait_until(
            lambda: all(self.sink.sensors.get(i, {}).get("count", 0) >= 3 for i in range(1, 9))))
        used = {self.sink.sensors[i]["node"] for i in range(1, 9)}
        self.assertGreater(len(used), 1)                   # sensory rozłożone po węzłach

    def test_awaria_wezla_sensor_przechodzi_dalej(self):
        n1 = self.add_node(1)
        self.add_node(2)
        s = self.add_sensor(14, seed=0)
        self.assertTrue(wait_until(lambda: s.node is not None))
        first = s.node
        victim = n1 if first == 1 else self.nodes[1]
        victim.stop()                                       # wyłączamy węzeł sensora
        self.nodes.remove(victim)
        self.assertTrue(wait_until(lambda: s.node != first, timeout=5))
        self.assertTrue(wait_until(lambda: self.sink.sensors[14]["node"] == s.node))

    # ---------- węzły jako osobne pliki NODExxx.TXT, które można wyłączać ----------
    def add_file_node(self, nid, **over):
        path = os.path.join(self.tmp.name, f"NODE{nid:03d}.TXT")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"ID={nid:03d}\nAKTYWNY={over.get('AKTYWNY', 1)}   # komentarz\n")
        n = Node(nid, sink_port=self.base, port=self.base + nid, log=lambda *_: None,
                 path=path, tick=TICK).start()
        n.file = path
        self.nodes.append(n)
        return n

    def test_plik_wezla(self):
        import steruj
        n = self.add_file_node(1)
        self.assertEqual(load_node_file(n.file), {"ID": 1, "AKTYWNY": 1})
        steruj.set_key(n.file, "AKTYWNY", 0)
        self.assertEqual(load_node_file(n.file)["AKTYWNY"], 0)
        bad = os.path.join(self.tmp.name, "wezel.txt")
        open(bad, "w").close()
        with self.assertRaises(ValueError):
            load_node_file(bad)

    def test_wylaczenie_i_wlaczenie_wezla(self):
        import steruj
        n = self.add_file_node(1)
        self.assertTrue(wait_until(lambda: 1 in self.sink.nodes))
        steruj.set_key(n.file, "AKTYWNY", 0)
        self.assertTrue(wait_until(lambda: 1 not in self.sink.nodes))
        steruj.set_key(n.file, "AKTYWNY", 1)
        self.assertTrue(wait_until(lambda: 1 in self.sink.nodes))

    def test_wezel_wylaczony_od_startu(self):
        n = self.add_file_node(2, AKTYWNY=0)
        time.sleep(4 * TICK)
        self.assertNotIn(2, self.sink.nodes)
        import steruj
        steruj.set_key(n.file, "AKTYWNY", 1)
        self.assertTrue(wait_until(lambda: 2 in self.sink.nodes))

    def test_wylaczony_wezel_zwalnia_miejsce_w_sieci(self):
        import steruj
        nodes = [self.add_file_node(i) for i in range(1, 5)]
        steruj.set_key(nodes[0].file, "AKTYWNY", 0)
        self.assertTrue(wait_until(lambda: 1 not in self.sink.nodes))
        self.add_node(5)                                    # jest miejsce na kolejny
        self.assertIn(5, self.sink.nodes)

    def test_sensor_przechodzi_gdy_wezel_wylaczony(self):
        import steruj
        n1 = self.add_file_node(1)
        n2 = self.add_file_node(2)
        s = self.add_sensor(31, seed=0)
        self.assertTrue(wait_until(lambda: s.node is not None))
        first = s.node
        victim = n1 if first == 1 else n2
        steruj.set_key(victim.file, "AKTYWNY", 0)
        self.assertTrue(wait_until(lambda: s.node not in (None, first), timeout=5))
        steruj.set_key(victim.file, "AKTYWNY", 1)
        self.assertTrue(wait_until(lambda: victim.id in self.sink.nodes))


if __name__ == "__main__":
    unittest.main(verbosity=2)
