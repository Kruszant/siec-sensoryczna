# Sieć sensoryczna – sensor temperatury, węzły, zlew (09.10.2026)

Implementacja w Pythonie 3 (tylko biblioteka standardowa). Elementy sieci
komunikują się przez TCP (localhost), wiadomości to obiekty JSON zakończone
znakiem nowej linii.

## 1. Architektura

```
 SENSOR 001 ─┐                          ┌───────────────────────────┐
 SENSOR 002 ─┼──► WĘZEŁ 1 (port 5001) ──┤                           │
 SENSOR 003 ─┘    WĘZEŁ 2 (port 5002) ──┤  ZLEW / SINK (port 5000)  │──► aplikacja (widok)
 SENSOR 004 ────► WĘZEŁ 3 (port 5003) ──┤  max 4 węzły              │──► pomiary.csv
 SENSOR 005 ────► WĘZEŁ 4 (port 5004) ──┤                           │
      ▲                                 └─────────────┬─────────────┘
      └──────────── "get_nodes" (lista aktywnych węzłów) ─┘   ← auto-przyłączenie
```

| Plik | Rola |
|---|---|
| `common.py` | protokół: wysyłanie/odczyt wiadomości JSON, stałe (porty, `MAX_NODES = 4`) |
| `sensor.py` | sensor temperatury: plik `SENSORxxx.TXT`, model liniowy, auto-przyłączenie, losowe odłączenia, przenoszenie |
| `node.py` | węzeł: unikalny nr, rejestracja w zlewie, przyjmowanie sensorów w dowolnej chwili, przekazywanie danych; własny plik `nodes/NODExxx.TXT` z przełącznikiem `AKTYWNY` |
| `sink.py` | zlew + aplikacja wyświetlająca: nr węzła, nr sensora, wynik, status, liczba przeniesień, log zdarzeń |
| `generuj_sensory.py` | tworzy pliki `sensors/SENSOR001.TXT …` z losowymi parametrami oraz `nodes/NODE001..004.TXT` |
| `uruchom_siec.py` | demo: zlew + węzły z `nodes/` + wszystkie sensory w jednym oknie |
| `steruj.py` | **ręczne** odłączanie / przyłączanie / przenoszenie sensora oraz wyłączanie / włączanie węzła (zmienia plik TXT) |
| `wykres_liniowosci.py` | wykresy SVG: punkty vs prosta najmniejszych kwadratów + reszty, R² (`zrzuty/6_liniowosc.svg`) |
| `test_siec.py` | testy automatyczne (unittest) |

## 2. Sensor (zadanie 1)

**Plik parametrów `SENSORxxx.TXT`** (xxx = unikalny numer, sprawdzany z polem `ID`):

```
ID=001
TYP=TEMPERATURA
JEDNOSTKA=C
T_START_MIN=-8          # losowa wartość startowa z przedziału
T_START_MAX=-3
NACHYLENIE_A=0.199      # współczynnik kierunkowy prostej [°C/s]
PRZESUNIECIE_MIN=0      # losowe przesunięcie X0 na charakterystyce [s]
PRZESUNIECIE_MAX=33
SZUM=0.0
OKRES_PROBKOWANIA=1.0   # pomiar co 1 s
# --- STEROWANIE RĘCZNE (sensor czyta ten plik co sekundę) ---
POLACZONY=1             # 1 = przyłączony, 0 = odłącz sensor od węzła
WEZEL=0                 # 0 = dowolny węzeł, 1..4 = przyłącz / przenieś do tego węzła
# --- opcjonalne odłączanie w losowych chwilach (0 = wyłączone) ---
P_ODLACZENIA=0
CZAS_ODLACZENIA_MIN=3   # [s]
CZAS_ODLACZENIA_MAX=8   # [s]
PRZENOSZENIE=1          # 1 = po losowym odłączeniu przyłącz do innego węzła
```

**Charakterystyka liniowa** (wzór prostej `y = a·x + b`):

```
T(k) = T_START + A · (X0 + k·Δt)
```

- `T_START` – losowa wartość startowa z `[T_START_MIN, T_START_MAX]`,
- `X0` – losowe przesunięcie na charakterystyce od wartości startowej,
- `A` – nachylenie, `k` – numer pomiaru, `Δt = 1 s`.

Sensor co sekundę wysyła kolejną wartość.

**Odłączanie ręczne.** Sensor co sekundę czyta ponownie swój plik `SENSORxxx.TXT`:

| zmiana w pliku | skutek |
|---|---|
| `POLACZONY=0` | sensor odłącza się od węzła i czeka (status ODŁĄCZ. w zlewie) |
| `POLACZONY=1` | sensor przyłącza się ponownie (auto-przyłączenie) |
| `WEZEL=3` | sensor przechodzi do węzła 3 – **przeniesienie** |
| `WEZEL=0` | sensor może być w dowolnym węźle |

Plik można zmienić w Notatniku (zapisz – zadziała w ciągu sekundy) albo
poleceniem `steruj.py` w drugim oknie terminala:

```bash
python steruj.py 2 odlacz        # sensor 002 -> POLACZONY=0
python steruj.py 2 przylacz      # sensor 002 -> POLACZONY=1
python steruj.py 5 przenies 4    # sensor 005 -> WEZEL=4
python steruj.py 5 auto          # sensor 005 -> WEZEL=0
python steruj.py 5 stan          # pokaż ustawienia
```

W czasie odłączenia charakterystyka „biegnie dalej”, więc po powrocie wartości
nadal leżą na tej samej prostej (na wykresie: przerwa w danych, ta sama prosta).
Dodatkowo `P_ODLACZENIA > 0` włącza odłączanie w losowych chwilach (domyślnie wyłączone).

**Auto-przyłączenie:** sensor pyta zlew o listę aktywnych węzłów (`get_nodes`),
losuje węzeł i wysyła `hello` ze swoim numerem; węzeł odpowiada `welcome`.
Jeśli węzłów jeszcze nie ma, sensor czeka i ponawia próbę. Gdy węzeł padnie,
sensor sam znajduje inny.

## 3. Węzeł (zadanie 2)

- unikalny numer, port `5000 + nr`,
- przy starcie rejestruje się w zlewie; zlew **odrzuca 5. węzeł** oraz węzeł o
  powtórzonym numerze,
- przyjmuje sensory w dowolnej chwili (serwer wielowątkowy),
- do każdego pomiaru dokleja swój numer i przekazuje go do zlewu,
- ma **własny plik** `nodes/NODExxx.TXT` (czytany co sekundę), który pozwala go wyłączać (patrz niżej),
- zgłasza `sensor_attached` / `sensor_detached` – dzięki temu zlew widzi
  **przenoszenie sensorów między węzłami**.

**Plik węzła `NODExxx.TXT`:**

```
ID=002
AKTYWNY=1     # 1 = węzeł działa, 0 = węzeł wyłączony (opuszcza sieć)
```

| zmiana w pliku | skutek |
|---|---|
| `AKTYWNY=0` | węzeł zrywa połączenia, wyrejestrowuje się ze zlewu (zwalnia miejsce z limitu 4); jego sensory same przechodzą do innego węzła |
| `AKTYWNY=1` | węzeł rejestruje się ponownie i znów przyjmuje sensory |

Można to zrobić w Notatniku albo poleceniem:

```bash
python steruj.py wezel 2 wylacz     # NODE002.TXT -> AKTYWNY=0
python steruj.py wezel 2 wlacz      # NODE002.TXT -> AKTYWNY=1
python steruj.py wezel 2 stan
```

Węzeł uruchomiony osobno z plikiem: `python node.py nodes/NODE002.TXT`
(`python node.py 2` działa jak dawniej – bez pliku, zawsze aktywny).

## 4. Zlew i aplikacja (zadanie 3)

Widok odświeżany co sekundę pokazuje: węzły w sieci (x/4) z liczbą sensorów,
tabelę **WĘZEŁ | SENSOR | TEMPERATURA | NR POMIARU | CZAS | STATUS | PRZENIESIENIA**
oraz log zdarzeń (przyłączenia, odłączenia, przeniesienia). Wszystkie pomiary
trafiają do `pomiary.csv`.

## 5. Uruchomienie

```bash
python generuj_sensory.py 6          # pliki sensors/SENSOR001..006.TXT i nodes/NODE001..004.TXT
python uruchom_siec.py               # wszystko w jednym oknie (10 min, Ctrl+C kończy)
python steruj.py 2 odlacz            # w DRUGIM oknie: ręczne sterowanie sensorami
python steruj.py wezel 2 wylacz      # ...i wyłączanie węzłów
```

albo osobno, w kilku terminalach:

```bash
python sink.py
python node.py nodes/NODE001.TXT   # ... NODE002..004 (albo: python node.py 1)  (node.py 5 zostanie odrzucony)
python sensor.py sensors/SENSOR001.TXT
```

## 6. Testy

```bash
python -m unittest -v test_siec
```

| Test | Co sprawdza |
|---|---|
| `test_wczytanie_parametrow`, `test_zla_nazwa_pliku`, `test_niezgodny_numer` | odczyt `SENSORxxx.TXT`, walidacja numeru |
| `test_start_losowy_w_przedziale` | losowy start i przesunięcie w zadanych przedziałach |
| `test_kolejne_wartosci_na_prostej` | pierwsza wartość = `T_START + A·X0`, stały przyrost = `A` |
| `test_max_4_wezly`, `test_duplikat_numeru_wezla` | limit 4 węzłów, unikalność numeru |
| `test_auto_przylaczenie_i_dane_w_zlewie` | sensor sam się przyłącza, zlew zna węzeł, sensor i wynik |
| `test_przylaczenie_gdy_wezel_pojawi_sie_pozniej` | węzeł przyjmuje sensor w dowolnej chwili |
| `test_reczne_odlaczenie_i_przylaczenie` | `POLACZONY=0` → sensor odłączony i nie wysyła danych; `POLACZONY=1` → wraca na tę samą prostą |
| `test_reczne_przeniesienie_do_wezla` | `WEZEL=3, 2, 4` → sensor przechodzi kolejno do wskazanych węzłów |
| `test_steruj_cli` | `steruj.py` poprawnie zmienia plik sensora |
| `test_odlaczanie_i_przenoszenie_miedzy_wezlami` | opcjonalny tryb losowy, przeniesienie zawsze do innego węzła |
| `test_wiele_sensorow_na_wielu_wezlach` | 8 sensorów rozłożonych na 4 węzłach |
| `test_awaria_wezla_sensor_przechodzi_dalej` | po wyłączeniu węzła sensor przechodzi do innego |
| `test_plik_wezla`, `test_wylaczenie_i_wlaczenie_wezla`, `test_wezel_wylaczony_od_startu` | plik `NODExxx.TXT`: `AKTYWNY=0/1` wyłącza i włącza węzeł |
| `test_wylaczony_wezel_zwalnia_miejsce_w_sieci` | wyłączony węzeł nie liczy się do limitu 4 |
| `test_sensor_przechodzi_gdy_wezel_wylaczony` | sensor przechodzi do innego węzła po wyłączeniu swojego |

Wynik: **20/20 testów OK** (w testach „sekunda” jest skrócona do 0,05 s).

## 7. Zrzuty ekranu

- `zrzuty/1_aplikacja_zlewu.png` – aplikacja zlewu w trakcie pracy sieci,
- `zrzuty/2_testy.png` – wynik testów,
- `zrzuty/3_plik_sensora.png` – przykładowy plik `SENSOR001.TXT`,
- `zrzuty/4_wykres_pomiarow.png` – pomiary z `pomiary.csv`: każdy sensor leży na
  swojej prostej, przerwy to odłączenia, kształt punktu to węzeł, który je przesłał,
- `zrzuty/5_reczne_sterowanie.png` – ręczne odłączanie i przenoszenie poleceniem `steruj.py`.
