# Plan: GNOME AI Panel

Repo: `gnome-ai-panel` (alternatywy: `ai-side-panel`, `acp-panel`)

Dokument dla agentów implementujących, testujących i UAT. Specyfikacja źródłowa: `.pipeline/SPEC.md` (odwołania typu „§3.3" wskazują sekcje specyfikacji).

## 1. Środowisko (zbadane 2026-11-10)

| Element | Stan |
|---|---|
| OS | Ubuntu 26.04.1 LTS, kernel 7.0, sesja **Wayland**, GNOME Shell **50.1** (Mutter 50) |
| Python | 3.14.4 systemowy, `python3-venv` zainstalowany, brak `pip` poza venv |
| PyGObject | 3.56.2 (`gi.events.GLibEventLoopPolicy` dostępne, natywne asyncio na pętli GLib) |
| GTK / libadwaita | GTK 4.22, Adw 1.9 (GI dostępne) |
| WebKitGTK | biblioteka `libwebkitgtk-6.0-4` 2.52.6 jest, **brak `gir1.2-webkit-6.0`** (do instalacji) |
| libsecret GI | `Secret-1` dostępne |
| GJS | 1.88.0 |
| Node / npm | v24.22.2 / 11.19.1 |
| Narzędzia | `gapplication`, `gdbus`, `gsettings`, `glib-compile-schemas`, `gnome-extensions`, `dbus-run-session`, `xauth`, `notify-send` są; **brak `Xvfb`**, brak `secret-tool`, brak `gh` |
| `gnome-shell` | obsługuje `--headless --wayland --no-x11 --virtual-monitor WxH` (e2e rozszerzenia) |
| Agenty | `kiro-cli` 2.26.0 w `~/.local/bin` (ma `kiro-cli acp`), brak `claude-agent-acp` |
| Monitor | jeden, 4096x2304 (HDMI-1) |
| Katalog projektu | tylko `gnome-ai-panel.md` i `.pipeline/` (brak repo git) |

### Kroki instalacji wykonywane ręcznie przez użytkownika (wymagają sudo)

```bash
sudo apt install gir1.2-webkit-6.0 xvfb libsecret-tools
# zależności systemowe przeglądarki Playwright (po `make setup`):
sudo npx playwright install-deps webkit
```

Opcjonalnie (tylko do ręcznego testu z prawdziwym Claude ACP): `npm install -g @agentclientprotocol/claude-agent-acp` oraz klucz `ANTHROPIC_API_KEY`. Opcjonalnie dla Kiro: `kiro-cli login`.

Wszystko inne robi `make setup` bez sudo (venv, pakiety pip, npm, przeglądarka Playwright).

## 2. Wymagania funkcjonalne

| ID | Wymaganie | Źródło w spec |
|---|---|---|
| FR-1 | Aplikacja działa w tle (`Gio.Application.hold()`), jedna instancja, panel otwiera się natychmiast | §3.1 |
| FR-2 | Okno bez dekoracji (`set_decorated(False)`), stały `application_id` `pl.local.AiPanel` | §1, §3.1 |
| FR-3 | Akcje `Gio.Action` przez D-Bus: `toggle`, `show`, `hide`, `new-chat`, `quit` (+ stanowe `visible`) | §3.1 |
| FR-4 | Interfejs czatu w `WebKit.WebView`, zasoby lokalne, bez CDN | §3.1, §3.2 |
| FR-5 | Markdown: listy, tabele, bloki kodu z podświetlaniem (highlight.js), przycisk kopiowania kodu | §1, §3.2 |
| FR-6 | Sanityzacja wyjścia modelu (DOMPurify) przed wstawieniem do DOM | §3.2, §6 |
| FR-7 | Pole wieloliniowe: Enter wysyła, Shift+Enter nowa linia; przycisk stop | §3.2 |
| FR-8 | Przyrostowe renderowanie strumienia odpowiedzi | §1, §3.2 |
| FR-9 | Zwijane bloki „myślenia" | §3.2 |
| FR-10 | Karty wywołań narzędzi (tytuł, status, wejście, wynik) | §1, §3.2 |
| FR-11 | Okienko zgody (Zezwól / Odrzuć) na prośby agenta; brak automatycznego zatwierdzania | §1, §3.2, §6 |
| FR-12 | Wybór agenta i modelu w nagłówku panelu | §3.2 |
| FR-13 | Motyw jasny/ciemny z systemu, nadpisywalny `chat.theme`; `chat.font_size` | §3.2, §5.3 |
| FR-14 | Linki otwierane w domyślnej przeglądarce, nigdy w panelu | §3.2 |
| FR-15 | Generyczny klient ACP: proces z konfiguracji (komenda, argumenty, env, cwd), JSON-RPC 2.0 po stdio linia po linii; `initialize` → `session/new` (cwd, serwery MCP) → `session/prompt` → `session/update` → koniec tury | §4.1 |
| FR-16 | Anulowanie tury (`session/cancel`) przyciskiem stop | §4.1 |
| FR-17 | Jeden proces na agenta, osobna sesja na rozmowę, restart procesu po awarii | §4.1 |
| FR-18 | Wspólny interfejs `Backend` i typy zdarzeń `TextDelta`, `ThinkingDelta`, `ToolCall`, `ToolUpdate`, `PermissionRequest`, `Done`, `Error` | §4 |
| FR-19 | `ApiBackend`: `POST` messages ze `stream: true`, nagłówki `x-api-key`, `anthropic-version`, `content-type`; SSE → zdarzenia; historia trzymana w aplikacji; konfigurowalne modele i prompt systemowy | §4.2 |
| FR-20 | Plik `~/.config/gnome-ai-panel/config.toml` (`default_agent`, `[agents.*]` typu `acp`/`api`, `[mcp.*]`, `[chat]`) z walidacją | §5.3 |
| FR-21 | Źródła wartości: `keyring`, `env`, `command`, `prompt`, `literal` | §5.3 |
| FR-22 | Zmiany pliku konfiguracji wczytywane bez restartu | §3.1, §5.3 |
| FR-23 | Zero założeń: nic nie zaszyte; pusta lista agentów → ekran „Dodaj agenta" | §1, §5.1 |
| FR-24 | Kreator agenta z szablonami (Kiro ACP, Claude ACP, Claude API, własny), które tylko wypełniają edytowalne pola | §5.1 |
| FR-25 | „Test połączenia": uruchomienie agenta, `initialize` (+ `session/new`), wynik albo czytelny błąd (brak komendy, zły klucz, nieobsługiwany protokół) | §3.1, §5.1 |
| FR-26 | Okno ustawień aplikacji: agenci (dodaj/edytuj/usuń), sekrety, serwery MCP, wygląd czatu | §3.1, §8.8 |
| FR-27 | Ostrzeżenie przy `literal` użytym dla klucza | §6 |
| FR-28 | Wyraźne oznaczenie trybu agenta z narzędziami (vs czysty czat) | §6 |
| FR-29 | Sesje w osobnym katalogu roboczym z konfiguracji (tworzony automatycznie, ścieżka absolutna) | §6 |
| FR-30 | Historia rozmów: JSON, jeden plik na rozmowę, w `chat.history_dir` | §5.3, §8.9 |
| FR-31 | Wiele rozmów: nowa rozmowa, lista, otwarcie, usunięcie | §8.9 |
| FR-32 | Wklejanie obrazków do promptu (gdy backend obsługuje) | §8.9 |
| FR-33 | Pokazywanie zużycia (tokeny/koszt), gdy backend je raportuje | §9 |
| FR-34 | Rozszerzenie: konfigurowalny skrót (`Main.wm.addKeybinding`) | §3.3 |
| FR-35 | Rozszerzenie: przełączanie przez akcję D-Bus `toggle`; uruchomienie aplikacji, jeśli nie działa | §3.3 |
| FR-36 | Pozycja: lewa/prawa krawędź, cała wysokość obszaru roboczego (z górnym paskiem), szerokość w px lub %, limity min/max | §1, §3.3 |
| FR-37 | Wybór monitora: `primary` / `pointer` / numer | §1, §3.3 |
| FR-38 | Okno na wszystkich pulpitach, na wierzchu, pominięte w Alt+Tab i w przeglądzie | §3.3 |
| FR-39 | Ikona w górnym pasku (`PanelMenu.Button`): lewy klik pokazuje/chowa, menu: nowa rozmowa, wybór agenta, ustawienia, zakończ; ikonę można wyłączyć | §1, §3.3 |
| FR-40 | Zwijanie po kliknięciu poza panelem (zdarzenie przepuszczane dalej); osobno włączane: utrata fokusu, Esc | §1, §3.3 |
| FR-41 | Przycisk „przypnij" w nagłówku wyłącza auto-zwijanie | §1, §3.3 |
| FR-42 | Animacja wsuwania/chowania, `animation-ms` (0 = wyłączona) | §3.3 |
| FR-43 | Zmiana szerokości przeciąganiem wewnętrznej krawędzi, zapis do ustawień | §1, §3.3 |
| FR-44 | Okno ustawień rozszerzenia (`prefs.js`, Adw); zmiany stosowane na żywo | §3.3, §5.2 |
| FR-45 | Schemat GSettings z kluczami z tabeli §3.3 | §3.3 |
| FR-46 | Serwery MCP z `[mcp.*]` przekazywane agentowi w `session/new` wg listy `mcp` agenta | §4.1, §5.3 |
| FR-47 | Opcjonalny serwer MCP „GNOME": powiadomienia, schowek; narzędzia z efektem ubocznym domyślnie wyłączone | §2, §6, §8.10 |
| FR-48 | Pakowanie natywne (skrypt instalacyjny, bez Flatpaka), autostart | §8.9, §9 |
| FR-49 | Klient ACP w terminalu (CLI): czat z dowolnym agentem z konfiguracji, wypisanie strumienia zdarzeń | §8.1 |
| FR-50 | Ograniczanie agentów wyłącznie konfiguracją (argumenty, `session_meta`, `system_prompt`) + przykładowe okrojone konfiguracje Kiro/Claude | §6 |

## 3. Wymagania niefunkcjonalne

- **NFR-1 Wydajność:** przy działającej aplikacji panel widoczny ≤ 300 ms od skrótu (bez animacji). Render strumienia dławiony do 1 klatki (`requestAnimationFrame`); odpowiedź 100 KB bez zawieszenia UI (test Playwright ≤ 2 s).
- **NFR-2 Bezpieczeństwo:** DOMPurify na wszystkim od modelu; CSP w `index.html` (`default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:`), brak zdalnych zasobów; nawigacja poza `file://…/app/ui/` blokowana. Klient ACP deklaruje `fs` i `terminal` = false. Brak auto-zgód (poza jawnym `--permission` w CLI deweloperskim, domyślnie `deny`). Polecenia (`command`, agenty) uruchamiane bez powłoki (`shlex.split`, `exec`). Sekrety nigdy w logach ani w plikach poza `literal`; logi JSON-RPC na poziomie DEBUG z redakcją `env`/`headers`. `config.toml` tworzony z `0600`, katalog `0700`; ostrzeżenie, gdy plik jest zapisywalny przez grupę/innych. Akcje debug dostępne tylko przy `AI_PANEL_DEBUG=1`.
- **NFR-3 Dostępność:** pełna obsługa klawiaturą (Tab, Enter, Esc), `aria-label` na przyciskach ikonowych, `role="dialog"` i fokus w okienku zgody, `aria-live="polite"` dla strumienia, fokus na polu wejściowym po pokazaniu panelu, kontrast WCAG AA w obu motywach.
- **NFR-4 Przenośność:** cel: GNOME 50 / Wayland (GNOME 50 nie ma sesji X11). `metadata.json` deklaruje `shell-version` 45–50, testowane tylko 50. Python ≥ 3.12.
- **NFR-5 Dane:** zapis atomowy (plik tymczasowy + `os.replace`) dla historii i konfiguracji; pole `version` w plikach historii; edycja konfiguracji z UI zachowuje komentarze (tomlkit).
- **NFR-6 Odporność:** limit linii stdio 16 MiB; nie-JSON w stdout agenta ignorowany (log DEBUG); nieznane typy `session/update` ignorowane; restart agenta z limitem 3 restarty / 60 s.
- **NFR-7 Logowanie:** `$XDG_STATE_HOME/gnome-ai-panel/app.log` (rotacja 1 MB × 3) + stderr; poziom przez `AI_PANEL_LOG_LEVEL` (domyślnie INFO).
- **NFR-8 Język:** UI po polsku; teksty UI w jednym miejscu (`app/ui/strings.js`, `app/strings.py`).

## 4. Wymagania niejawne

- Walidacja konfiguracji z komunikatami z „ścieżką" (`agents.x.command: wymagane`); błędny wpis wyłącza tylko ten wpis; błąd składni → zostaje ostatnia poprawna konfiguracja + baner błędu w UI.
- Brak pliku konfiguracji = pusta, poprawna konfiguracja (nie tworzyć pliku bez akcji użytkownika).
- Puste stany: brak agentów („Dodaj agenta"), pusta rozmowa (podpowiedź), pusta historia.
- Błędy czytelne w czacie: brak komendy, timeout startu (`startup_timeout_s`, domyślnie 20), proces zakończony (kod + ostatnie 20 linii stderr), `auth_required` (lista `authMethods` z podpowiedzią logowania w terminalu), HTTP 401/429/5xx, brak sieci.
- Blokada wysyłania podczas trwającej tury (przycisk stop zamiast wyślij).
- Rozwijanie `~` i zmiennych w ścieżkach; `cwd` tworzony (`0700`).
- Zmiana konfiguracji działającego agenta → proces restartowany przy następnej nowej sesji (trwająca tura nie jest przerywana).
- Zamknięcie aplikacji (`quit`) kończy procesy agentów (SIGTERM, po 3 s SIGKILL).
- Izolacja testów: osobna szyna D-Bus i katalogi XDG, żeby testy nie dotykały pulpitu ani danych użytkownika.

## 5. Niejasności i otwarte pytania (z przyjętym założeniem)

| # | Pytanie | Założenie w planie |
|---|---|---|
| Q1 | Wersja GNOME, tylko Wayland? (§10) | GNOME 50 na Waylandzie (maszyna docelowa). Metadane 45–50, testy tylko na 50. |
| Q2 | Pamiętać rozmowy między uruchomieniami? (§10) | Tak: JSON w `history_dir` (etap S9). Ponowne otwarcie rozmowy ACP używa `session/load`, jeśli agent ma `loadSession`; inaczej nowa sesja z komunikatem, że agent nie pamięta kontekstu. |
| Q3 | Claude: wystarczy API czy ACP od początku? (§10) | Oba: generyczny klient ACP od S2, szablon Claude ACP w S8, `ApiBackend` w S7. Testy automatyczne na fałszywym agencie; prawdziwy Claude ACP tylko w ręcznym smoke teście. |
| Q4 | Panel na każdym monitorze? (§10) | Jeden panel, monitor z ustawienia `monitor`. |
| Q5 | Domyślny skrót | `['<Super>i']` (decyzja użytkownika przy akceptacji planu). Spec podaje `Super+A` tylko jako przykład, a na Ubuntu `Super+A` zajmuje „Pokaż aplikacje" (`org.gnome.shell.keybindings toggle-application-view` = `['<Super>a']` na maszynie docelowej). Sprawdzenie z 2026-11-10: `gsettings list-recursively \| grep -i "<super>i"` nie zwraca nic, więc `<Super>i` jest wolny w `org.gnome.desktop.wm.keybindings`, `org.gnome.shell.keybindings`, `org.gnome.settings-daemon.plugins.media-keys` i `org.gnome.mutter.keybindings`. Zapas, gdyby S5-T1 wykrył konflikt: `['<Super><Shift>a']` (zapisany w PLAN i README). README pokazuje, jak zmienić skrót. Rozszerzenie loguje ostrzeżenie, gdy rejestracja skrótu się nie uda. |
| Q6 | Identyfikatory | App ID `pl.local.AiPanel` (ścieżka D-Bus `/pl/local/AiPanel`), UUID rozszerzenia `gnome-ai-panel@pl.local`, schemat `org.gnome.shell.extensions.gnome-ai-panel`. |
| Q7 | Wersja ACP | Protokół v1 (`protocolVersion: 1`); v2 (draft) poza zakresem. Własna cienka warstwa JSON-RPC zamiast SDK (uzasadnienie w §7). |
| Q8 | Uwierzytelnianie ACP (`authenticate`) | Panel nie prowadzi przepływów logowania; przy `auth_required` pokazuje metody i podpowiedź (np. „zaloguj się w terminalu"). |
| Q9 | `Adw.PreferencesWindow` jest przestarzałe w Adw ≥ 1.6 | Używamy `Adw.PreferencesDialog` (ten sam wygląd). |
| Q10 | Wartości domyślne `ApiBackend` | `anthropic_version = "2023-06-01"`, `max_tokens = 4096`, oba nadpisywalne w konfiguracji; endpoint i model zawsze z konfiguracji (szablon je wypełnia). |
| Q11 | „Test połączenia" dla agenta API | Minimalne żądanie (`max_tokens: 1`, prompt „ping"); w UI informacja, że zużywa pojedyncze tokeny. |
| Q12 | Esc w panelu | Zwija panel (gdy `collapse-on-escape` i panel nieprzypięty, i nie jest otwarte okienko zgody); przerwanie tury tylko przyciskiem stop. |
| Q13 | Okrojony agent Kiro | Przykładowy plik `data/examples/kiro/ai-panel-chat.json` + instrukcja w README; panel nie tworzy go sam. Szablon Kiro: `command = "kiro-cli"`, `args = ["acp"]`, `cwd = "~/.cache/ai-panel"`. |
| Q14 | Ograniczenia Claude ACP | Generyczne pole `session_meta` (tabela TOML wysyłana jako `_meta` w `session/new`); szablon Claude ACP wypełnia je listą wyłączonych narzędzi. Implementer weryfikuje nazwę klucza w README `claude-agent-acp`. |
| Q15 | Schowek dla serwera MCP | Przez aplikację panelu (D-Bus, `Gdk.Clipboard`), nie przez gnome-shell; zapis schowka tylko z flagą `--allow-write`. |
| Q16 | Język UI | Polski. |
| Q17 | Zmiana szerokości przeciąganiem | Uchwyt GTK w aplikacji (`Gdk.Toplevel.begin_resize`), rozszerzenie zapisuje nową szerokość (px, z limitami) do GSettings. |

## 6. Poza zakresem

- Osobne panele na wielu monitorach; synchronizacja historii; funkcje IDE (diffy, edycja projektów) (§1).
- Flatpak/Snap; tray StatusNotifierItem dla innych środowisk niż GNOME (§9).
- ACP v2, terminal auth, metody klienta `fs/*` i `terminal/*` (świadomie wyłączone ze względów bezpieczeństwa), `elicitation`.
- Import konfiguracji z zewnętrznych źródeł.
- Tłumaczenia inne niż polski.
- Testy na GNOME < 50 i na X11.

## 7. Ryzyka i ograniczanie

| Ryzyko | Ograniczenie |
|---|---|
| asyncio na pętli GLib (podprocesy) w PyGObject 3.56 / Python 3.14 (polityki pętli są przestarzałe) | S1-T2 zawiera test, że `asyncio.create_subprocess_exec` działa na `GLibEventLoop`. Rdzeń (config, backendy) jest czystym asyncio, testowanym bez GTK. Plan B: pętla asyncio w wątku roboczym + `GLib.idle_add`. |
| WebKitGTK pod Xvfb w testach | `WEBKIT_DISABLE_COMPOSITING_MODE=1`, `LIBGL_ALWAYS_SOFTWARE=1`; logika UI testowana w Playwright bez GTK; testy GTK tylko jako cienka warstwa integracyjna. |
| Playwright WebKit na Ubuntu 26.04 | Zmienna `PW_BROWSER=chromium` jako zapas (UI używa tylko standardowego DOM). |
| `captured-event` dla okien Wayland, ukrywanie z Alt+Tab/przeglądu przez wstrzykiwanie w wewnętrzne klasy Shella | Czysta logika w `extension/lib/` z testami gjs; e2e na `gnome-shell --headless`; utrata fokusu jako wyzwalacz zapasowy; `InjectionManager` z czystym `disable()`. |
| Nowe rozszerzenie na Waylandzie wymaga ponownego logowania | e2e w zagnieżdżonym `gnome-shell --headless`; na realnej sesji jeden krok `[manual]`. |
| Zmiany ACP | `protocolVersion` 1 przypięty; tolerancyjne parsowanie (nieznane pola/typy pomijane); fałszywy agent odwzorowuje przykłady JSON ze spec ACP. |
| Wyciek sekretów | Redakcja w logach, test jednostkowy sprawdzający, że wartość sekretu nie pojawia się w logu i komunikatach błędów. |
| Konflikt domyślnego skrótu z systemowym (`Super+A` = „Pokaż aplikacje" na Ubuntu) | Domyślnie `<Super>i` (Q5); S5-T1 sprawdza brak konfliktu przez `gsettings`, zapas `<Super><Shift>a`. |
| Klik w ikonę paska zwija i rozwija panel | Klik na aktorze przycisku wyłączony z logiki „poza panelem" (test gjs funkcji `shouldCollapse`). |

## 8. Decyzje techniczne

| Decyzja | Alternatywy | Wybór i powód |
|---|---|---|
| Język aplikacji | Python + PyGObject; Rust + gtk-rs; GJS | **Python + PyGObject**: wymagany przez spec (§3.1), już zainstalowany (3.56), najprostszy, testy w pytest. Rust: dłuższa kompilacja, większy próg. GJS: słabszy ekosystem testów/HTTP. |
| Pętla async | `gi.events.GLibEventLoopPolicy` (natywne w PyGObject ≥ 3.50); `gbulb`; wątki + `GLib.idle_add` | **Natywne asyncio PyGObject**: `gbulb` jest porzucony, wątki komplikują anulowanie. Wątki jako plan B (ryzyko w §7). |
| Klient ACP | SDK `agent-client-protocol` (Pydantic); własna cienka warstwa JSON-RPC | **Własna warstwa** (~300 linii): bez Pydantic i ciągłych zmian wersji SDK, pełna kontrola nad parsowaniem tolerancyjnym i redakcją logów, łatwe testy z fałszywym agentem. Spec dopuszcza oba (§4.1). |
| HTTP dla `ApiBackend` | `httpx` (async stream); `urllib` w wątku; libsoup przez GI | **httpx**: dojrzały, asynchroniczny streaming, działa na każdej pętli asyncio, prosty mock przez lokalny serwer. |
| Konfiguracja TOML | `tomllib` (tylko odczyt) + `tomli-w`; `tomlkit` | **tomlkit**: odczyt i zapis z zachowaniem komentarzy użytkownika (plik jest też edytowany ręcznie). |
| Sekrety | `keyring` (pip); libsecret przez GI (`Secret-1`) | **libsecret przez GI**: już zainstalowane, bez dodatkowej zależności, natywne dla GNOME. Za interfejsem `SecretStore` z atrapą w testach. |
| Obserwacja pliku | `watchdog`; `Gio.FileMonitor` | **Gio.FileMonitor**: wbudowane, działa na pętli GLib. |
| UI czatu | WebKitGTK + marked/highlight.js/DOMPurify; natywne widżety GTK (GtkTextView) | **WebKitGTK** zgodnie ze spec: markdown/tabele/kod jak w claude.ai, testowalne w Playwright. |
| Biblioteki JS | CDN; npm + kopiowanie do `app/ui/vendor/` | **npm + vendoring** (pliki w repo, skrypt `npm run vendor`): spec wymaga braku CDN, runtime nie potrzebuje Node. |
| Testy Python | pytest + pytest-asyncio; unittest | **pytest + pytest-asyncio**: standard, fikstury dla fałszywych agentów. |
| Testy UI | Playwright (Node) na `index.html` z atrapą mostu; testy tylko przez GTK | **Playwright** (WebKit; zapas Chromium): szybkie, deterministyczne, bez GTK. GTK pokryte kilkoma testami integracyjnymi pod Xvfb. |
| Testy rozszerzenia | gjs + własny mini-runner; Jasmine (jak w gnome-shell) | **gjs + mini-runner** (`tests/gjs/run.js`, ~40 linii) dla czystej logiki w `extension/lib/`; e2e przez `gnome-shell --headless`. Bez dodatkowych zależności. |
| Lint | ruff + ESLint (flat config); tylko ruff | **ruff** (Python: check + format) i **ESLint** (JS w `app/ui/` i `extension/`), plus `glib-compile-schemas --strict --dry-run`. |
| Ekran testowy GUI | Xvfb (`xvfb-run`); `weston --backend=headless`; `gnome-shell --headless` | **Xvfb** dla aplikacji GTK (proste, `GDK_BACKEND=x11`); **gnome-shell --headless** tylko dla e2e rozszerzenia (potrzebny Mutter). |

Zależności Pythona (venv z `--system-site-packages`, żeby widzieć `gi`):
- runtime (`requirements.txt`): `httpx==0.28.*`, `tomlkit==0.13.*`
- dev (`requirements-dev.txt`): `-r requirements.txt`, `pytest==9.*`, `pytest-asyncio==1.*`, `ruff==0.*` (przypiąć dokładne wersje przy S1-T1)

Zależności npm (`package.json`, devDependencies, przypięte dokładnie przez `package-lock.json`): `marked`, `highlight.js`, `dompurify`, `@playwright/test`, `eslint`, `globals`.

## 9. Architektura

```
gnome-shell (GJS)                      Aplikacja pl.local.AiPanel (Python, GTK4)
┌──────────────────────────┐ D-Bus     ┌──────────────────────────────────────────────┐
│ extension.js             │ org.gtk.  │ main.py: Adw.Application (hold), akcje       │
│  keybinding, ikona/menu  │ Actions   │ window.py: okno bez dekoracji, WebView,      │
│  pozycjonowanie, zwijanie├──────────►│            uchwyt resize, polityka linków    │
│  animacja, prefs.js      │◄──────────┤ bridge.py: JS⇄Python (JSON)                  │
│  lib/ (czysta logika)    │ Changed   │ controller.py: rozmowy, wybór agenta, zgody  │
│  DebugIface (GetState)   │           │ config.py / secrets.py / storage.py          │
└──────────────────────────┘           │ backends/: base, jsonrpc, acp, api           │
                                       └──────┬───────────────────────────┬───────────┘
                                              │ stdio JSON-RPC            │ HTTPS SSE
                                       agenty ACP (dowolne)          endpoint API
```

Zasady:
- `config`, `secrets`, `storage`, `backends`, `controller` nie importują GTK/WebKit (testowalne czystym pytest). GTK tylko w `main.py`, `window.py`, `bridge.py`, `settings_ui.py`, `clipboard_service.py`.
- `controller.py` przyjmuje obiekt `UiSink` (metoda `dispatch(event_dict)`); w GUI implementuje go `bridge.py`, w testach lista.
- Rozszerzenie steruje aplikacją wyłącznie przez `org.gtk.Actions` na `pl.local.AiPanel` / `/pl/local/AiPanel` (`Gio.DBusActionGroup`) i obserwuje sygnał `Changed` (stany `visible`, `pinned`, `agent`, `agents`).
- Aplikacja sama nie pozycjonuje okna (Wayland); bez rozszerzenia jest zwykłym oknem bez dekoracji.

## 10. Struktura repozytorium

```
gnome-ai-panel/
├── Makefile                  # kanoniczne komendy (sekcja Commands)
├── README.md
├── .gitignore  .env.example  pyproject.toml (ruff, pytest)  requirements.txt  requirements-dev.txt
├── package.json  package-lock.json  eslint.config.mjs  playwright.config.mjs
├── app/
│   ├── __init__.py  __main__.py   # python -m app  → main.main()
│   ├── main.py               # Adw.Application, akcje, pętla asyncio
│   ├── window.py             # okno, WebView, uchwyt resize, polityka nawigacji
│   ├── bridge.py             # UserContentManager ⇄ evaluate_javascript
│   ├── controller.py         # rozmowy, agenci, zgody, historia
│   ├── config.py             # config.toml: model, walidacja, ścieżki, zapis (tomlkit)
│   ├── secrets.py            # źródła keyring/env/command/prompt/literal
│   ├── templates.py          # szablony agentów (Kiro ACP, Claude ACP, Claude API, własny)
│   ├── storage.py            # historia rozmów (JSON)
│   ├── settings_ui.py        # Adw.PreferencesDialog
│   ├── clipboard_service.py  # D-Bus dla serwera MCP (S11)
│   ├── strings.py  logging_setup.py
│   ├── cli.py                # python -m app.cli …
│   ├── backends/ base.py jsonrpc.py acp.py api.py
│   └── ui/ index.html app.js render.js chat.js strings.js style.css vendor/
├── mcp/gnome_mcp.py          # serwer MCP „GNOME" (S11)
├── extension/
│   ├── metadata.json extension.js prefs.js stylesheet.css
│   ├── lib/ geometry.js monitor.js collapse.js appProxy.js
│   └── schemas/org.gnome.shell.extensions.gnome-ai-panel.gschema.xml
├── data/ pl.local.AiPanel.desktop  pl.local.AiPanel.svg  examples/
├── scripts/ check-deps.sh run.sh run-headless.sh stop.sh install.sh uninstall.sh shell-e2e.sh vendor.mjs
└── tests/
    ├── conftest.py
    ├── unit/                 # pytest bez GTK
    ├── integration/          # pytest: CLI, fałszywe agenty, GTK pod Xvfb (marker gui)
    ├── e2e/test_shell.py     # gnome-shell --headless (make test-shell)
    ├── fakes/ fake_acp_agent.py fake_anthropic.py
    ├── ui/*.spec.mjs         # Playwright + ui/mock-bridge.js
    └── gjs/ run.js *.test.js
```

## 11. Model danych

### 11.1 Konfiguracja (`config.py`, dataclasses)

```python
ValueSource = Keyring(name) | Env(name) | Command(cmd, timeout_s=10) | Prompt(label=None) | Literal(value)

AcpAgent:  id, type="acp", name (opc., domyślnie id), command (wymagane), args=[], cwd (wymagane w praktyce; brak → błąd walidacji),
           env: dict[str, ValueSource]={}, startup_timeout_s=20, mcp: list[str]=[],
           session_meta: dict|None, system_prompt: str|None
ApiAgent:  id, type="api", name, endpoint (wymagane), model (wymagane), models: list[str]=[model],
           system_prompt=None, api_key: ValueSource (opc.), max_tokens=4096, anthropic_version="2023-06-01"
McpServer: id, command, args=[], env: dict[str, ValueSource]={}
ChatConfig: font_size=14, theme="system"|"light"|"dark", history_dir="~/.local/share/gnome-ai-panel"
Config:    default_agent: str|None, agents: dict[id, Agent], mcp: dict[id, McpServer], chat, errors: list[ConfigError]
ConfigError: path ("agents.x.command"), message
```

Ścieżka pliku: `$AI_PANEL_CONFIG` lub `$XDG_CONFIG_HOME/gnome-ai-panel/config.toml` (domyślnie `~/.config/...`).

### 11.2 Zdarzenia backendu (`backends/base.py`)

```python
TextDelta(text)                ThinkingDelta(text)
ToolCall(id, title, kind, status, raw_input, content)      ToolUpdate(id, status?, title?, raw_input?, content?)
PermissionRequest(request_id, tool_call_id, title, kind, raw_input, options=[PermissionOption(id, name, kind)])
ConfigOptions(options=[...])   Usage(used, size, cost_amount?, cost_currency?)
Done(stop_reason)              Error(message, kind="spawn"|"timeout"|"protocol"|"auth"|"http"|"crashed"|"other")
```

`Backend` (Protocol): `name`, `async new_session() -> str`, `send(session_id, prompt: list[ContentPart]) -> AsyncIterator[Event]`, `respond_permission(request_id, option_id | None)` (None = odrzucenie/cancelled), `async cancel(session_id)`, `async set_option(session_id, config_id, value)`, `async close()`. `ContentPart` = `{"type":"text","text":…}` lub `{"type":"image","mimeType":…,"data":base64}`. Rozszerzenie `respond_permission` względem spec (option_id zamiast bool) wynika z ACP (opcje definiuje agent).

### 11.3 Historia (`storage.py`)

`<history_dir>/<conversation_id>.json` (id = `YYYYMMDD-HHMMSS-<6 hex>`), uprawnienia `0600`:

```json
{"version": 1, "id": "...", "agent_id": "...", "title": "pierwsze 60 znaków", "created": "ISO8601", "updated": "ISO8601",
 "acp_session_id": "sess_… | null",
 "messages": [{"role": "user|assistant", "parts": [...], "thinking": "...", "tools": [{"id","title","status","input","output"}], "stop_reason": "end_turn"}]}
```

## 12. Interfejsy

### 12.1 Akcje D-Bus aplikacji (`org.gtk.Actions` na `/pl/local/AiPanel`)

| Akcja | Parametr | Stan | Znaczenie |
|---|---|---|---|
| `toggle`, `show`, `hide` | – | – | widoczność okna |
| `visible` | – | `b` (tylko odczyt) | czy okno jest widoczne |
| `new-chat` | – | – | nowa rozmowa |
| `quit` | – | – | zakończ (zabija procesy agentów) |
| `agent` | `s` | `s` | bieżący agent (id); zmiana → nowa rozmowa |
| `agents` | – | `a(ss)` (tylko odczyt) | lista (id, nazwa) do menu w pasku |
| `pinned` | – | `b` (SetState) | przypięcie (ustawiane z nagłówka lub z zewnątrz) |
| `collapse-on-escape` | – | `b` (SetState) | ustawiane przez rozszerzenie |
| `side` | – | `s` (SetState) | `left`/`right`, ustawiane przez rozszerzenie (strona uchwytu) |
| `preferences` | – | – | okno ustawień aplikacji (w S6: otwiera `config.toml` domyślnym edytorem) |
| `debug-send` | `s` | – | tylko `AI_PANEL_DEBUG=1`: wpisuje tekst i wysyła |
| `debug-click` | `s` | – | tylko debug: klik w selektor CSS |
| `debug-dump` | – | – | tylko debug: zapisuje `$XDG_STATE_HOME/gnome-ai-panel/debug-dump.json` |

Przykład: `gapplication action pl.local.AiPanel toggle`; stan: `gdbus call --session -d pl.local.AiPanel -o /pl/local/AiPanel -m org.gtk.Actions.Describe visible`.

`debug-dump.json`: `{"visible": bool, "screen": "empty|chat|history|add-agent", "agent": id, "badge": "tools|chat", "messages": [{"role","text","html","thinking","tools":[{"title","status"}]}], "permission_dialog": {"open": bool, "title": str} , "banner": str|null, "theme": "light|dark", "pinned": bool}`.

### 12.2 Most JS ⇄ Python (JSON)

JS → Python (`window.webkit.messageHandlers.bridge.postMessage(obj)`): `ready`, `send {text, images?}`, `cancel`, `permission {request_id, option_id|null}`, `select_agent {id}`, `set_option {config_id, value}`, `new_chat`, `open_link {url}`, `pin {value}`, `escape`, `history_list`, `history_open {id}`, `history_delete {id}`, `open_settings`, `secret_prompt_reply {token, value|null}`, `dump {state}`.

Python → JS (`window.aiPanel.dispatch(obj)`): `init {agents, current, config_errors, theme, font_size, strings}`, `turn_start`, `text_delta`, `thinking_delta`, `tool_call`, `tool_update`, `permission_request`, `config_options`, `usage`, `done {stop_reason}`, `error {message, kind}`, `conversation {id, messages}`, `history {items}`, `secret_prompt {token, label}`, `banner {text|null}`, `pinned {value}`, `request_dump`.

### 12.3 CLI (`python -m app.cli`, w Makefile `make cli ARGS="…"`)

| Komenda | Działanie | Kod wyjścia |
|---|---|---|
| `check-config [--config P]` | waliduje, wypisuje błędy `ścieżka: komunikat` | 0 ok / 1 błędy |
| `agents [--json]` | lista agentów (id, typ, nazwa, poprawny?) | 0 |
| `test-agent ID` | to samo co „Test połączenia" | 0 ok / 2 błąd |
| `chat ID PROMPT [--json] [--permission deny\|allow] [--cancel-after S]` | jedna tura, strumień zdarzeń na stdout (`--json`: JSON Lines) | 0 Done / 2 Error |
| `secret set NAME` (wartość z stdin) / `secret delete NAME` / `secret has NAME` | keyring | 0 / 1 |
| `history list [--json]` / `history show ID` | historia | 0 |
| `ui-dump` | aktywuje `debug-dump` i wypisuje plik | 0 / 1 |

### 12.4 Rozszerzenie: interfejs debug D-Bus

Obiekt `/org/gnome/Shell/Extensions/GnomeAiPanel`, interfejs `org.gnome.Shell.Extensions.GnomeAiPanel` na nazwie `org.gnome.Shell`: metody `Toggle()` (ta sama ścieżka kodu co skrót), `GetState() -> s` (JSON: `{"visible", "rect":[x,y,w,h], "monitor", "workArea":[…], "pinned", "trayIcon": bool, "keybinding": [...], "skipTaskbar": bool, "sticky": bool, "above": bool}`), oraz metody tylko dla klucza `debug` = true: `SimulateClick(x, y)` (przepuszcza punkt przez logikę zwijania), `SimulateResize(width)` (zmienia rozmiar okna jak przeciągnięcie uchwytu), `ActivateMenuItem(id)` (pozycja menu w pasku). `Toggle` i `GetState` są wystawiane zawsze; `GetState` tylko odczytuje.

### 12.5 GSettings `org.gnome.shell.extensions.gnome-ai-panel`

`side` (s, `right`), `width` (s, `480`; format `^\d+%?$`), `min-width` (i, 320), `max-width` (i, 900), `monitor` (s, `primary`), `shortcut` (as, `['<Super>i']`; zapas `['<Super><Shift>a']` przy konflikcie, zob. Q5), `show-tray-icon` (b, true), `collapse-on-click-outside` (b, true), `collapse-on-focus-loss` (b, false), `collapse-on-escape` (b, true), `animation-ms` (i, 180, zakres 0–1000), `debug` (b, false).

## 13. Konfiguracja i sekrety

- Sekrety tylko przez źródła `keyring` / `env` / `command` / `prompt`; `literal` dozwolony, ale ostrzegany w UI i w `check-config`, gdy nazwa zmiennej pasuje do `KEY|TOKEN|SECRET|PASSWORD` (bez rozróżniania wielkości liter).
- Keyring: schemat libsecret `pl.local.AiPanel.Secret`, atrybut `name`.
- Zmienne środowiskowe aplikacji: `AI_PANEL_CONFIG` (ścieżka konfiguracji), `AI_PANEL_LOG_LEVEL`, `AI_PANEL_DEBUG` (akcje debug), `AI_PANEL_DEFAULT_AGENT` (nadpisuje `default_agent`), `AI_PANEL_URI_LOG` (testy: zapis URI do pliku zamiast otwierania przeglądarki), `AI_PANEL_SKIP_EXTENSION_INSTALL` (testy instalatora), `PW_BROWSER` (testy). Opisane w `.env.example` (bez sekretów; `ANTHROPIC_API_KEY=` puste z komentarzem, że to przykład dla źródła `env`).
- Agent dostaje środowisko: `os.environ` sesji + rozwiązane wpisy `env` (wpis nadpisuje). Wartości nigdy nie są logowane.

## Commands

Wszystkie agenty używają dokładnie tych komend z katalogu głównego repo. Wszystkie są nieinteraktywne.

| Komenda | Działanie |
|---|---|
| `make setup` | `scripts/check-deps.sh` (sprawdza `gir1.2-webkit-6.0`, `Xvfb`, `xvfb-run`, `gjs`, `node`, `glib-compile-schemas`; brak → lista `sudo apt install …` i kod 1), `python3 -m venv --system-site-packages .venv`, `.venv/bin/pip install -r requirements-dev.txt`, `npm ci`, `npx playwright install webkit chromium` |
| `make build` | `glib-compile-schemas extension/schemas`, `python -m compileall -q app mcp`, `gnome-extensions pack extension --force --extra-source=lib --out-dir=dist` → `dist/gnome-ai-panel@pl.local.shell-extension.zip` |
| `make lint` | `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `npx eslint app/ui extension tests/ui tests/gjs`, `glib-compile-schemas --strict --dry-run extension/schemas` |
| `make test` | pełny zestaw, kod ≠ 0 przy błędzie: `make test-py test-gjs test-ui` |
| `make test-py` | `xvfb-run -a -s "-screen 0 1920x1080x24" dbus-run-session -- .venv/bin/pytest -q` (unit + integracyjne + GUI; izolowane XDG w fiksturach) |
| `make test-gjs` | `gjs -m tests/gjs/run.js` (czysta logika rozszerzenia) |
| `make test-ui` | `npx playwright test` (przeglądarka z `PW_BROWSER`, domyślnie `webkit`) |
| `make test-shell` | `scripts/shell-e2e.sh`: `dbus-run-session` + `gnome-shell --headless --wayland --no-x11 --virtual-monitor 1920x1080`, izolowane `HOME`/`XDG_*` w `.run/shell-home`, instaluje i włącza rozszerzenie, uruchamia aplikację, odpala `.venv/bin/pytest tests/e2e -q`. Nie wchodzi do `make test` (cięższe); uruchamiane w UAT S5/S6. |
| `make run` | `scripts/run.sh`: uruchamia aplikację w tle na bieżącej sesji (`.venv/bin/python -m app`), PID w `.run/app.pid`, log w `.run/app.log`; czeka maks. 10 s na linię `ui ready` w logu |
| `make run-headless` | `scripts/run-headless.sh`: Xvfb + prywatna szyna D-Bus + izolowane `XDG_*` w `.run/home`, `AI_PANEL_DEBUG=1`, zapisuje zmienne do `.run/headless.env`, czeka na `ui ready`. Użycie: `source .run/headless.env && gapplication action pl.local.AiPanel toggle` |
| `make stop` | `scripts/stop.sh`: `gapplication action pl.local.AiPanel quit` (dla obu trybów), po 3 s SIGTERM procesów z `.run/*.pid` (app, Xvfb, dbus); usuwa pliki pid; kod 0 również, gdy nic nie działa |
| `make cli ARGS="…"` | `.venv/bin/python -m app.cli $(ARGS)` (z `make run-headless`: najpierw `source .run/headless.env`) |
| `make install` / `make uninstall` | instalacja użytkownika (bez sudo): kod do `~/.local/share/gnome-ai-panel`, venv tam, `~/.local/bin/gnome-ai-panel`, plik `.desktop` i ikona, rozszerzenie przez `gnome-extensions install --force dist/…zip` |
| `make vendor` | `node scripts/vendor.mjs`: kopiuje `marked`, `highlight.js` (+ motywy CSS), `dompurify` z `node_modules` do `app/ui/vendor/` |

Konwencje testów w skryptach UAT:
- Konfiguracja testowa: plik wskazany przez `AI_PANEL_CONFIG`; fałszywy agent: `command = ".venv/bin/python"`, `args = ["tests/fakes/fake_acp_agent.py", "--scenario", "<nazwa>"]` (ścieżki absolutne lub względem repo; config loader rozwija względne ścieżki względem katalogu pliku konfiguracji).
- Scenariusze fałszywego agenta ACP: `echo` (odpowiada „Echo: <prompt>" w 3 fragmentach, markdown z tabelą i blokiem kodu przy promptach zaczynających się od `md:`), `thinking`, `tool`, `permission`, `slow` (fragment co 200 ms przez 10 s, honoruje `session/cancel`), `crash` (exit 3 po `session/prompt`, stderr „boom"), `crash-once` (jak `crash`, ale tylko przy pierwszym prompcie; marker w `cwd`), `bad-version` (odpowiada `protocolVersion: 99`), `auth` (`session/new` → błąd `-32000 auth_required`), `noise` (nie-JSON w stdout), `models` (`configOptions` z kategorią `model`), `load` (`loadSession: true`), `usage`, `image` (`promptCapabilities.image: true`, opisuje otrzymany obraz), `env` (odpowiada wartością zmiennej podanej w prompt; tylko do testów sekretów). Każdy scenariusz `tool` wysyła też fragment myślenia. Flaga `--record PLIK` zapisuje parametry otrzymanych `initialize`/`session/new`/`session/load`/`session/prompt` jako JSON Lines.
- Fałszywe API: `tests/fakes/fake_anthropic.py --port 0` wypisuje `PORT=<n>` i serwuje SSE w formacie Anthropic Messages; tryby przez nagłówek klucza: `sk-test-ok`, `sk-test-401`, `sk-test-429`, `sk-test-thinking`, `sk-test-slow`.

## 14. Strategia testów

| Poziom | Narzędzie | Gdzie | Co |
|---|---|---|---|
| Unit Python | pytest, pytest-asyncio | `tests/unit/` | config, secrets (atrapa keyringu), jsonrpc, mapowanie zdarzeń ACP i SSE, controller z atrapą backendu i `UiSink`, storage, szablony |
| Integracja Python | pytest | `tests/integration/` | AcpBackend ⇄ `fake_acp_agent.py`, ApiBackend ⇄ `fake_anthropic.py`, CLI jako podproces, GTK+WebKit pod Xvfb (marker `gui`): start aplikacji jako podproces z izolowaną szyną i `AI_PANEL_DEBUG=1`, sterowanie przez `gapplication`/`gdbus`, asercje na `debug-dump.json` |
| UI | Playwright | `tests/ui/*.spec.mjs` | `app/ui/index.html` przez `file://` z `tests/ui/mock-bridge.js` (rejestruje `postMessage`, pozwala wywołać `aiPanel.dispatch`): markdown, sanityzacja XSS, strumień, karty, zgody, nagłówek, historia |
| Unit GJS | gjs | `tests/gjs/` | `extension/lib/*.js`: geometria, wybór monitora, decyzja o zwinięciu, parsowanie szerokości |
| E2E Shell | gnome-shell --headless + pytest | `tests/e2e/` | rozszerzenie + aplikacja: Toggle, geometria, strona, szerokość, zwijanie (SimulateClick), ustawienia na żywo przez `gsettings` |
| Ręczne | – | README „Smoke test" | prawdziwy pulpit: skrót, animacja, wygląd; prawdziwe `kiro-cli acp` |

Zasady: każdy task dodaje testy; `make test` musi przejść po każdym tasku. Testy nigdy nie używają prawdziwej szyny sesji, prawdziwego keyringu ani `~/.config` użytkownika (fikstura `isolated_env` ustawia `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`, `XDG_CACHE_HOME` na `tmp_path`). Test z prawdziwym libsecret pomijany (`skip`), gdy brak usługi Secret Service.

## 15. Etapy (szczegóły w `TASKS.md`)

| Etap | Wartość dla użytkownika | Tasków |
|---|---|---|
| S1 Szkielet | aplikacja startuje w tle, okno bez dekoracji z lokalną stroną, sterowanie akcjami D-Bus, działające `make test` | 3 |
| S2 Konfiguracja i klient ACP w terminalu | rozmowa z dowolnym agentem ACP z `config.toml` z terminala, sekrety z keyring/env/komendy, „test połączenia" w CLI | 5 |
| S3 Okno czatu | pisanie w panelu i strumieniowa odpowiedź z markdownem, podświetlaniem i kopiowaniem kodu | 4 |
| S4 Pełna obsługa ACP w UI | myślenie, karty narzędzi, okienka zgody, stop, czytelne błędy, wybór agenta i modelu | 4 |
| S5 Rozszerzenie: podstawy | skrót pokazuje panel przyklejony do krawędzi, na całą wysokość, poza Alt+Tab | 4 |
| S6 Rozszerzenie: interakcja | ikona w pasku z menu, zwijanie po kliknięciu obok/Esc, przypinanie, animacja, zmiana szerokości, okno ustawień na żywo | 4 |
| S7 Czysty czat API | szybki czat przez API Anthropic bez narzędzi | 2 |
| S8 Okno ustawień aplikacji | dodawanie agentów z szablonów, sekrety, MCP, wygląd i „Test połączenia" bez edycji pliku; przeładowanie pliku na żywo | 5 |
| S9 Historia i wiele rozmów | rozmowy zapisane między uruchomieniami, lista i powrót, wklejanie obrazków, zużycie tokenów | 4 |
| S10 Instalacja i autostart | instalacja jedną komendą, start z sesją w tle, dokumentacja okrojonych agentów | 2 |
| S11 Serwer MCP „GNOME" | agenty mogą wysłać powiadomienie i odczytać/zapisać schowek (za zgodą) | 2 |

## 16. Śledzenie wymagań (FR → taski)

| FR | Taski | FR | Taski |
|---|---|---|---|
| FR-1 | S1-T2, S1-T3, S10-T1 | FR-26 | S8-T2, S8-T3 |
| FR-2 | S1-T2 | FR-27 | S2-T1, S8-T3 |
| FR-3 | S1-T2, S1-T3, S3-T3 | FR-28 | S4-T4, S7-T2 |
| FR-4 | S1-T2, S3-T1 | FR-29 | S2-T4 |
| FR-5 | S3-T1 | FR-30 | S9-T1 |
| FR-6 | S3-T1 | FR-31 | S9-T2 |
| FR-7 | S3-T2 | FR-32 | S9-T3 |
| FR-8 | S3-T2, S3-T4 | FR-33 | S9-T4 |
| FR-9 | S4-T1 | FR-34 | S5-T2, S6-T4 |
| FR-10 | S4-T1 | FR-35 | S5-T2, S5-T4 |
| FR-11 | S4-T2 | FR-36 | S5-T1, S5-T2, S5-T4 |
| FR-12 | S4-T4, S7-T2 | FR-37 | S5-T1, S5-T2, S5-T4 |
| FR-13 | S3-T4 | FR-38 | S5-T3, S5-T4 |
| FR-14 | S3-T4 | FR-39 | S6-T1 |
| FR-15 | S2-T3, S2-T4 | FR-40 | S6-T2 |
| FR-16 | S2-T4, S4-T3 | FR-41 | S6-T2 |
| FR-17 | S2-T4, S4-T3 | FR-42 | S6-T3 |
| FR-18 | S2-T3 | FR-43 | S6-T3 |
| FR-19 | S7-T1, S7-T2 | FR-44 | S6-T4 |
| FR-20 | S2-T1 | FR-45 | S5-T1 |
| FR-21 | S2-T2, S8-T5 | FR-46 | S2-T4, S8-T3 |
| FR-22 | S8-T1 | FR-47 | S11-T1, S11-T2 |
| FR-23 | S2-T1, S3-T3, S8-T4 | FR-48 | S5-T2, S10-T1 |
| FR-24 | S8-T2, S8-T4 | FR-49 | S2-T5 |
| FR-25 | S2-T5, S8-T4, S7-T2 | FR-50 | S2-T4, S10-T2 |
