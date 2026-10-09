"""Wspólne elementy sieci sensorycznej: protokół (JSON w liniach przez TCP)."""
import json
import socket

HOST = "127.0.0.1"
SINK_PORT = 5000          # zlew (sink)
NODE_BASE_PORT = 5000     # węzeł nr N słucha na porcie NODE_BASE_PORT + N
MAX_NODES = 4             # maksymalna liczba węzłów w sieci


def send_msg(sock: socket.socket, msg: dict) -> None:
    """Wysyła jedną wiadomość JSON zakończoną znakiem nowej linii."""
    sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))


class LineReader:
    """Odczyt kolejnych wiadomości JSON z gniazda (jedna linia = jedna wiadomość)."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.buf = b""

    def read(self):
        """Zwraca słownik albo None, gdy połączenie zostało zamknięte."""
        while b"\n" not in self.buf:
            try:
                chunk = self.sock.recv(4096)
            except OSError:
                return None
            if not chunk:
                return None
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))


def request(port: int, msg: dict, host: str = HOST, timeout: float = 2.0):
    """Jednorazowe zapytanie-odpowiedź (np. pytanie zlewu o listę węzłów)."""
    with socket.create_connection((host, port), timeout=timeout) as s:
        send_msg(s, msg)
        return LineReader(s).read()
