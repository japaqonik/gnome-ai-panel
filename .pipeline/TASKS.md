# Tasks: GNOME AI Panel
Repo: gnome-ai-panel

Wspólne zasady dla każdego taska: po zakończeniu `make lint` i `make test` kończą się kodem 0. Komendy, ścieżki, identyfikatory i konwencje fałszywych agentów są w `.pipeline/PLAN.md` (sekcje „Commands", §11–§13). Testy nigdy nie dotykają `~/.config` użytkownika, prawdziwej szyny sesji ani keyringu.

## S1: Szkielet aplikacji
Value: Aplikacja `pl.local.AiPanel` startuje w tle jako jedna instancja, pokazuje okno bez dekoracji z lokalną stroną czatu (ekran „Dodaj agenta") i daje się sterować akcjami D-Bus; projekt ma działające `setup`/`lint`/`test`/`run`/`stop`.

### S1-T1: Repozytorium, narzędzia i pierwszy test
- Status: [x]
- Depends on: -
- Requirements: S1 setup
- Scope: `git init` (gałąź `main`); `.gitignore` (`.venv/`, `node_modules/`, `.run/`, `dist/`, `__pycache__/`, `*.compiled`, `extension/schemas/gschemas.compiled`, `test-results/`, `playwright-report/`, `.env`); `.env.example` (zmienne z PLAN §13, bez wartości sekretów); `Makefile` ze wszystkimi celami z sekcji Commands (cele jeszcze bez implementacji wypisują „not implemented yet" i kończą się 0, poza `setup`, `lint`, `test`, `test-py`); `scripts/check-deps.sh`; `pyproject.toml` (ruff: line-length 100, target py312; pytest: `testpaths = ["tests"]`, `asyncio_mode = "auto"`, marker `gui`); `requirements.txt`, `requirements-dev.txt` z dokładnymi wersjami; `package.json` + `package-lock.json` (devDependencies z PLAN §8), `eslint.config.mjs` (globale browser dla `app/ui`, GJS dla `extension`), `playwright.config.mjs` (`testDir: tests/ui`, przeglądarka z `PW_BROWSER`, domyślnie webkit); `app/__init__.py` z `__version__ = "0.1.0"`; `tests/conftest.py` z fiksturą `isolated_env` (HOME i XDG_* w `tmp_path`); `tests/unit/test_version.py`; `tests/gjs/run.js` (mini-runner: importuje `*.test.js`, liczy porażki, `imports.system.exit(1)` przy błędzie) z `tests/gjs/sanity.test.js`; README (cel, wymagania systemowe z `sudo apt install …`, `make setup`, `make test`, `make run`).
- Done when:
  - `make setup` → kod 0 (po ręcznej instalacji pakietów apt z PLAN §1); bez `Xvfb` → kod 1 i wypisane `sudo apt install xvfb`
  - `make lint` → kod 0
  - `make test` → kod 0; pytest raportuje ≥ 1 passed, `gjs` runner wypisuje `1 passed`, Playwright bez testów nie powoduje błędu (`--pass-with-no-tests`)
  - `git status --porcelain` nie pokazuje plików z `.venv/` ani `node_modules/`
- Tests: `test_version` (wersja jest stringiem semver); `sanity.test.js` (runner wykrywa porażkę: osobny test runnera uruchamia `gjs` na pliku z celowym błędem i oczekuje kodu ≠ 0).

### S1-T2: Aplikacja GTK z WebView i akcjami D-Bus
- Status: [x]
- Depends on: S1-T1
- Requirements: FR-1, FR-2, FR-3, FR-4
- Scope: `app/__main__.py`, `app/main.py` (`Adw.Application(application_id="pl.local.AiPanel")`, `hold()`, pętla asyncio przez `gi.events.GLibEventLoopPolicy`, akcje `toggle`/`show`/`hide`/`new-chat`/`quit` + stanowa `visible` (b), opcja `--background` = start bez pokazywania okna), `app/window.py` (`Adw.ApplicationWindow`, `set_decorated(False)`, domyślny rozmiar 480×900, `WebKit.WebView` ładujący `app/ui/index.html` przez `file://`, ukrywanie zamiast niszczenia przy zamknięciu), `app/bridge.py` (rejestracja handlera `bridge`, odbiór `ready` → log `ui ready`), `app/logging_setup.py` (plik w `$XDG_STATE_HOME/gnome-ai-panel/app.log` + stderr, `AI_PANEL_LOG_LEVEL`), `app/ui/index.html` (CSP z PLAN NFR-2, ekran pusty „Brak skonfigurowanych agentów — Dodaj agenta" z identyfikatorem `#empty-state`), `app/ui/app.js` (wysyła `ready`), `app/ui/style.css`.
- Done when:
  - `xvfb-run -a dbus-run-session -- .venv/bin/python -m app` uruchomione w tle loguje `ui ready` w ≤ 10 s
  - `.venv/bin/python -c "import app.main"` działa bez wyświetlacza (import nie tworzy okna)
  - `make lint` i `make test` → kod 0
- Tests: `tests/unit/test_asyncio_glib.py`: na `GLibEventLoop` działa `asyncio.create_subprocess_exec("true")` i `asyncio.sleep` (wynik determinuje plan B z PLAN §7 – jeśli test nie przejdzie, implementer przełącza na wątek roboczy i dokumentuje to w README); `tests/unit/test_actions.py`: lista zarejestrowanych akcji i typ stanu `visible` (bez okna, `Gio.Application` nie rejestrowana na szynie).

### S1-T3: run/stop, tryb headless i test integracyjny
- Status: [x]
- Depends on: S1-T2
- Requirements: FR-1, FR-3
- Scope: `scripts/run.sh`, `scripts/run-headless.sh` (Xvfb `-displayfd`, `dbus-daemon --session --fork --print-address`, izolowane XDG w `.run/home`, zapis `.run/headless.env` z `DISPLAY`, `DBUS_SESSION_BUS_ADDRESS`, `XDG_*`, `AI_PANEL_DEBUG=1`, `GDK_BACKEND=x11`), `scripts/stop.sh` zgodnie z sekcją Commands; cele Makefile `run`, `run-headless`, `stop`; `tests/integration/conftest.py` z fiksturą `app_process` (start aplikacji jako podproces w bieżącym środowisku testu, czekanie na `ui ready`, sprzątanie); `tests/integration/test_app_actions.py` (marker `gui`); `tests/ui/smoke.spec.mjs` + `tests/ui/mock-bridge.js`.
- Done when:
  - `make run-headless` → kod 0, plik `.run/headless.env` istnieje
  - `source .run/headless.env && gapplication action pl.local.AiPanel show && gdbus call --session -d pl.local.AiPanel -o /pl/local/AiPanel -m org.gtk.Actions.Describe visible` → wynik zawiera `true`
  - `make stop` → kod 0, brak procesów `python -m app` i Xvfb z `.run/*.pid`; drugi `make stop` → kod 0
  - `make test` → kod 0
- Tests: integracja: `toggle` zmienia `visible` false→true→false; drugie uruchomienie `python -m app` przy działającej instancji kończy się kodem 0 i nie tworzy drugiego procesu-głównego (jedna instancja); `quit` kończy proces w ≤ 5 s. Playwright: strona ładuje się, `#empty-state` widoczny, `meta[http-equiv=Content-Security-Policy]` obecny, mostek otrzymał `{type:"ready"}`.

### UAT S1
- UAT-S1-1: Given świeży klon i zainstalowane pakiety systemowe When uruchamiam `make setup && make lint && make test` Then wszystkie trzy kończą się kodem 0
  - Verify: `make setup; echo $?; make lint; echo $?; make test; echo $?` → trzy razy `0`
- UAT-S1-2: Given aplikacja uruchomiona headless When aktywuję `toggle` dwa razy Then stan `visible` zmienia się na `true`, a potem `false`
  - Verify: `make run-headless && source .run/headless.env && gapplication action pl.local.AiPanel toggle && gdbus call --session -d pl.local.AiPanel -o /pl/local/AiPanel -m org.gtk.Actions.Describe visible` → zawiera `true`; ponownie `toggle` i `Describe` → zawiera `false`; `grep -c "ui ready" .run/home/state/gnome-ai-panel/app.log` → ≥ 1
- UAT-S1-3: Given działająca aplikacja When wywołuję `make stop` Then proces kończy się, a powtórne `make stop` nie zgłasza błędu
  - Verify: `make stop; echo $?` → `0`; `pgrep -f "python -m app"` → brak wyniku; `make stop; echo $?` → `0`
- UAT-S1-4: Given sesja GNOME użytkownika When `make run` i `gapplication action pl.local.AiPanel show` Then pojawia się okno bez paska tytułowego z napisem „Dodaj agenta" `[manual]`
  - Verify: `make run && gapplication action pl.local.AiPanel show`; obejrzeć okno; `make stop`

## S2: Konfiguracja i klient ACP w terminalu
Value: Użytkownik wpisuje dowolnego agenta ACP (np. `kiro-cli acp`) do `config.toml`, z sekretami z keyringu/env/komendy, i rozmawia z nim z terminala (`make cli ARGS="chat …"`), widząc strumień zdarzeń; `test-agent` mówi czytelnie, co jest nie tak.

### S2-T1: Wczytywanie i walidacja config.toml
- Status: [x]
- Depends on: S1-T1
- Requirements: FR-20, FR-23, FR-27
- Scope: `app/config.py`: model danych z PLAN §11.1 (bez `ValueSource` rozwiązywania – tylko parsowanie), ścieżka z `AI_PANEL_CONFIG`/XDG, parsowanie tomlkit, rozwijanie `~` i ścieżek względnych (względem katalogu pliku), walidacja (wymagane pola, typy, nieznany `type`, nieznany `source`, `mcp` odwołujące się do nieistniejącego `[mcp.x]`, nieznany `default_agent`, `width` itp.) zwracająca listę `ConfigError(path, message)`; błędny agent pomijany, reszta działa; brak pliku = pusta konfiguracja; ostrzeżenie `literal` dla nazw pasujących do `KEY|TOKEN|SECRET|PASSWORD`; ostrzeżenie o uprawnieniach pliku (group/other writable). `app/cli.py` z komendami `check-config` i `agents [--json]`.
- Done when:
  - `AI_PANEL_CONFIG=/nonexistent make cli ARGS="agents --json"` → `[]`, kod 0
  - `make cli ARGS="check-config --config tests/data/config_invalid.toml"` → kod 1, wypisuje linię zaczynającą się od `agents.broken.command:`
  - `make cli ARGS="check-config --config tests/data/config_valid.toml"` → kod 0
- Tests: unit `tests/unit/test_config.py`: przykład z SPEC §5.3 parsuje się (2 agenci, 1 MCP, chat); brak pliku; pusty plik; błąd składni TOML → jeden `ConfigError` z numerem linii; każdy rodzaj błędu walidacji; `default_agent` pusty dozwolony; rozwijanie `~`; ostrzeżenie `literal` dla `SOME_API_KEY`, brak ostrzeżenia dla `PLAIN_VALUE`; ostrzeżenie uprawnień przy `0666`.

### S2-T2: Źródła wartości i sekrety
- Status: [x]
- Depends on: S2-T1
- Requirements: FR-21
- Scope: `app/secrets.py`: `SecretStore` (Protocol) + `LibsecretStore` (GI `Secret`, schemat `pl.local.AiPanel.Secret`, atrybut `name`) + `MemoryStore` (testy); `resolve(source, *, store, prompt_cb) -> str|None` dla `keyring`, `env`, `command` (`shlex.split`, bez powłoki, timeout 10 s, obcięcie końcowego `\n`, błąd z kodem wyjścia, bez stdout w komunikacie), `prompt` (async callback; w CLI: `getpass` gdy TTY, inaczej błąd „wymaga interakcji"), `literal`; `resolve_env(agent) -> dict[str,str]`; brak wartości dla zmiennej opcjonalnej nie jest błędem (zmienna pomijana, log INFO z nazwą, nie wartością). CLI: `secret set NAME` (stdin), `secret delete NAME`, `secret has NAME`. Filtr logowania redagujący znane wartości sekretów.
- Done when:
  - `printf 'abc' | make cli ARGS="secret set test-x"` w środowisku bez Secret Service → kod 1 i komunikat „brak usługi Secret Service" (nie traceback)
  - `make test` → kod 0
- Tests: unit: każde źródło; `command` z `printf secret` → `secret`; `command` z `false` → błąd bez wartości; `command` z timeoutem (`sleep 20`, timeout 0.5 s); `env` brak zmiennej → `None`; test redakcji: wartość sekretu nie występuje w przechwyconym logu ani w `str(error)`; integracja `LibsecretStore` pomijana, gdy brak usługi.

### S2-T3: Transport JSON-RPC po stdio i fałszywy agent ACP
- Status: [x]
- Depends on: S1-T1
- Requirements: FR-15, FR-18
- Scope: `app/backends/base.py` (zdarzenia i `Backend` z PLAN §11.2); `app/backends/jsonrpc.py`: `JsonRpcConnection(reader, writer)` – wysyłanie żądań z korelacją `id`, powiadomień, obsługa przychodzących żądań (handler zwraca wynik lub błąd JSON-RPC), przychodzących powiadomień, limit linii 16 MiB, ignorowanie linii nie-JSON (log DEBUG), błąd wszystkich oczekujących żądań przy EOF, logowanie ruchu na DEBUG z redakcją pól `env`/`headers`. `tests/fakes/fake_acp_agent.py`: samodzielny skrypt (tylko stdlib) implementujący scenariusze z PLAN „Commands".
- Done when:
  - `printf '%s\n' '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1}}' | .venv/bin/python tests/fakes/fake_acp_agent.py --scenario echo` → linia JSON z `"protocolVersion": 1`
  - `make test` → kod 0
- Tests: unit na parze potoków w pamięci: korelacja odpowiedzi poza kolejnością, błąd JSON-RPC → wyjątek z kodem, przychodzące żądanie → odpowiedź, linia `garbage` pominięta, linia 1 MiB przechodzi, EOF → oczekujące żądania kończą się wyjątkiem `ConnectionClosed`, redakcja `env` w logu.

### S2-T4: AcpBackend
- Status: [x]
- Depends on: S2-T2, S2-T3
- Requirements: FR-15, FR-16, FR-17, FR-29, FR-46, FR-50
- Scope: `app/backends/acp.py`: start procesu (`asyncio.create_subprocess_exec`, argv z `command`+`args`, env = sesja + `resolve_env`, `cwd` tworzony `0700`), `initialize` (`protocolVersion: 1`, `clientCapabilities: {fs:{readTextFile:false,writeTextFile:false}, terminal:false}`, `clientInfo`), timeout `startup_timeout_s`, odrzucenie innej wersji (Error kind `protocol`); `new_session()` → `session/new` z absolutnym `cwd`, `mcpServers` z listy `mcp` (env jako lista `{name,value}`), `_meta` = `session_meta`, `systemPrompt` (append) tylko gdy agent ogłasza `sessionCapabilities.systemPrompt`; `send()` → `session/prompt` i mapowanie `session/update` (`agent_message_chunk`→TextDelta, `agent_thought_chunk`→ThinkingDelta, `tool_call`→ToolCall, `tool_call_update`→ToolUpdate, `config_option_update`→ConfigOptions, `usage_update`→Usage, reszta ignorowana) z routingiem po `sessionId`; `session/request_permission` → PermissionRequest i oczekiwanie na `respond_permission`; `cancel()` → `session/cancel` + odpowiedź `cancelled` na oczekujące zgody; wynik → Done(stopReason); `auth_required` → Error kind `auth` z listą `authMethods`; brak komendy → Error kind `spawn` („Nie znaleziono polecenia: …"); koniec procesu w trakcie tury → Error kind `crashed` z kodem i ostatnimi 20 liniami stderr; ponowny start przy następnym `new_session` (limit 3/60 s); `close()` SIGTERM → 3 s → SIGKILL. Jeden proces na agenta (rejestr w `app/backends/__init__.py`: `get_backend(agent_cfg)`).
- Done when:
  - `make test` → kod 0, testy integracyjne AcpBackend przechodzą w ≤ 30 s łącznie
- Tests: integracja z fałszywym agentem: `echo` (kolejność i treść TextDelta, Done `end_turn`), `thinking`, `tool` (ToolCall + 2 ToolUpdate), `permission` (allow → tool `completed`; reject → `failed`/odmowa), `slow` + cancel (Done `cancelled` ≤ 2 s), `crash` (Error `crashed` zawiera `boom`, kolejna sesja działa po restarcie), `bad-version`, `auth`, `noise`, brak komendy, timeout startu (`sleep 30` jako komenda, timeout 1 s), dwie sesje równolegle w jednym procesie z poprawnym routingiem, `mcpServers` i `_meta` trafiają do `session/new` (fałszywy agent zapisuje otrzymane params do pliku wskazanego `--record`), sekret z `env` trafia do środowiska procesu (scenariusz `env`).

### S2-T5: CLI: chat i test-agent
- Status: [x]
- Depends on: S2-T4
- Requirements: FR-49, FR-25
- Scope: `app/cli.py`: `chat ID PROMPT [--json] [--permission deny|allow] [--cancel-after S]` (tekst na stdout na bieżąco, myślenie/narzędzia/zgody jako linie z prefiksem `[thinking]`, `[tool]`, `[permission]`; `--json` = JSON Lines zdarzeń; domyślnie zgody odrzucane z komunikatem), `test-agent ID` (wspólna funkcja `app/diagnostics.py:test_agent(cfg) -> TestResult(ok, agent_info, protocol_version, auth_methods, error)` wykonująca start, `initialize`, `session/new`, zamknięcie; czytelne komunikaty po polsku dla każdego typu błędu). Konfiguracja przykładowa `tests/data/config_fake.toml`: `default_agent = "fake-echo"` i po jednym agencie `fake-<scenariusz>` dla każdego scenariusza z PLAN „Commands” (`fake-echo`, `fake-thinking`, `fake-tool`, `fake-perm`, `fake-slow`, `fake-crash`, `fake-crash-once`, `fake-badver`, `fake-auth`, `fake-noise`, `fake-models`, `fake-load`, `fake-usage`, `fake-image`, `fake-env` z `SECRET_VAR = {source="command", cmd="printf s3cr3t-value"}`) oraz `fake-missing` (`command = "/nonexistent/agent"`). Ścieżki względne rozwijane względem katalogu pliku.
- Done when:
  - `AI_PANEL_CONFIG=tests/data/config_fake.toml make cli ARGS="chat fake-echo 'Cześć'"` → stdout zawiera `Echo: Cześć`, kod 0
  - `AI_PANEL_CONFIG=tests/data/config_fake.toml make cli ARGS="test-agent fake-echo"` → kod 0, wypisuje nazwę i wersję agenta oraz `protokół: 1`
  - `AI_PANEL_CONFIG=tests/data/config_fake.toml make cli ARGS="test-agent fake-missing"` → kod 2, komunikat zawiera `Nie znaleziono polecenia`
- Tests: integracja CLI jako podproces: każdy agent z `config_fake.toml`; `--json` daje poprawny JSON w każdej linii, ostatnia linia `{"type":"done",...}`; `--permission deny` domyślne; `--cancel-after 0.5` na `slow` → `stop_reason` `cancelled`; nieznane ID → kod 2 i lista dostępnych agentów.

### UAT S2
- UAT-S2-1: Given `config_fake.toml` z fałszywym agentem echo When uruchamiam czat z terminala Then widzę strumień odpowiedzi i kod 0
  - Verify: `AI_PANEL_CONFIG=tests/data/config_fake.toml make cli ARGS="chat fake-echo 'Cześć' --json"` → każda linia to JSON, występuje `"type": "text_delta"`, ostatnia linia zawiera `"stop_reason": "end_turn"`
- UAT-S2-2: Given agent z błędną komendą, złą wersją protokołu i wymaganym logowaniem When uruchamiam `test-agent` dla każdego Then każdy kończy się kodem 2 z innym, czytelnym komunikatem po polsku
  - Verify: `for a in fake-missing fake-badver fake-auth; do AI_PANEL_CONFIG=tests/data/config_fake.toml make -s cli ARGS="test-agent $a"; echo "rc=$?"; done` → trzy różne komunikaty (brak polecenia / nieobsługiwana wersja protokołu / wymagane logowanie z listą metod), trzy razy `rc=2`, brak tracebacków
- UAT-S2-3: Given niepoprawny plik konfiguracji When `check-config` Then dostaję listę błędów ze ścieżkami i kod 1, a poprawne wpisy są nadal widoczne w `agents`
  - Verify: `make cli ARGS="check-config --config tests/data/config_invalid.toml"; echo $?` → linie `agents.broken.command: …`, `1`; `AI_PANEL_CONFIG=tests/data/config_invalid.toml make cli ARGS="agents --json"` → zawiera poprawnego agenta, nie zawiera `broken`
- UAT-S2-4: Given sekret ze źródła `command` When czatuję z agentem `fake-env` Then agent dostaje wartość, a log nie zawiera sekretu
  - Verify: `AI_PANEL_CONFIG=tests/data/config_fake.toml make cli ARGS="chat fake-env SECRET_VAR"` → stdout zawiera `s3cr3t-value`; `grep -r s3cr3t-value "${XDG_STATE_HOME:-$HOME/.local/state}/gnome-ai-panel/" ; echo $?` → `1`
- UAT-S2-5: Given zalogowany `kiro-cli` When dodaję agenta `kiro` (`command="kiro-cli"`, `args=["acp"]`, `cwd="~/.cache/ai-panel"`) i uruchamiam czat Then dostaję odpowiedź od Kiro `[manual]`
  - Verify: `make cli ARGS="test-agent kiro"` → kod 0; `make cli ARGS="chat kiro 'Powiedz OK'"` → odpowiedź tekstowa

## S3: Okno czatu
Value: Użytkownik pisze w oknie panelu i dostaje strumieniową odpowiedź skonfigurowanego agenta z markdownem, tabelami, podświetlonym kodem i przyciskiem kopiowania; linki otwierają się w przeglądarce, motyw zgadza się z systemem.

### S3-T1: Biblioteki JS i renderowanie markdown
- Status: [x]
- Depends on: S1-T3
- Requirements: FR-4, FR-5, FR-6
- Scope: `scripts/vendor.mjs` + cel `make vendor`; pliki w `app/ui/vendor/` (`marked.esm.js` lub UMD, `highlight.min.js` z popularnymi językami, `github.min.css` i `github-dark.min.css`, `purify.min.js`) wraz z plikami licencji; `app/ui/render.js`: `renderMarkdown(text) -> string` (marked GFM → DOMPurify z zakazem `style`, `on*`, `iframe`, `form`; linki dostają `rel="noopener noreferrer"` i `data-external`), `enhanceCodeBlocks(container)` (highlight.js + przycisk „Kopiuj" `aria-label="Kopiuj kod"` korzystający z `navigator.clipboard`, zmiana etykiety na „Skopiowano" na 1,5 s); `tests/ui/render.spec.mjs`.
- Done when:
  - `make vendor && git status --porcelain app/ui/vendor` → brak zmian (pliki w repo zgodne z lockiem)
  - `npx playwright test tests/ui/render.spec.mjs` → wszystkie testy passed
  - `grep -rE "https?://" app/ui/index.html app/ui/*.js` → brak odwołań do zasobów zdalnych (kod 1)
- Tests: Playwright: lista, tabela GFM (element `table` z 2 wierszami), blok ```python ma klasę `hljs` i przycisk kopiowania; kliknięcie kopiuje treść (`context.grantPermissions(['clipboard-read','clipboard-write'])`); XSS: `<img src=x onerror=alert(1)>`, `<script>`, `[a](javascript:alert(1))` → brak skryptu i atrybutów `on*`, brak `href="javascript:`; 100 KB markdown renderuje się w ≤ 2 s.

### S3-T2: Interakcje czatu w UI (atrapa mostu)
- Status: [x]
- Depends on: S3-T1
- Requirements: FR-7, FR-8
- Scope: `app/ui/chat.js` + zmiany `index.html`/`app.js`/`style.css`/`strings.js`: układ (nagłówek, lista wiadomości `aria-live="polite"`, pole `textarea#prompt` auto-rozszerzane do 8 linii, przycisk `#send`/`#stop`), Enter wysyła (`{type:"send",text}`), Shift+Enter nowa linia, pusty prompt nie wysyła, w trakcie tury przycisk stop (`{type:"cancel"}`) i blokada wysyłania; obsługa `dispatch`: `init`, `turn_start`, `text_delta` (dopisywanie do bufora i render throttlowany `requestAnimationFrame`), `done` (koniec tury; `cancelled` → znacznik „Przerwano"), `error` (dymek błędu z `kind`); ekran pusty gdy `init.agents` puste; przewijanie do dołu, chyba że użytkownik przewinął w górę.
- Done when:
  - `npx playwright test tests/ui/chat.spec.mjs` → passed
  - `make test` → kod 0
- Tests: Playwright: Enter → mostek dostał `send`; Shift+Enter → nowa linia, brak `send`; 50 delt `text_delta` → jedna wiadomość asystenta z pełnym tekstem; podczas tury `#stop` widoczny, `#send` ukryty, Enter nie wysyła; klik stop → `cancel`; `done` przywraca `#send`; `error` pokazuje komunikat; `init` z pustymi agentami → `#empty-state`.

### S3-T3: Controller i połączenie mostu z backendem
- Status: [x]
- Depends on: S2-T4, S3-T2
- Requirements: FR-3, FR-23
- Scope: `app/controller.py`: `ChatController(config, ui_sink, backend_factory)` – wybór agenta (`default_agent` lub pierwszy poprawny; brak → `init` z pustą listą), utrzymanie bieżącej rozmowy (lista wiadomości w pamięci), obsługa `send` (tworzy sesję leniwie, iteruje zdarzenia backendu, wysyła do UI `turn_start`/`text_delta`/`done`/`error`), `cancel`, `new_chat` (nowa sesja), błędy konfiguracji w `init.config_errors`; `app/bridge.py`: parsowanie wiadomości JS (walidacja typu i pól, nieznane → log WARNING), `dispatch` przez `evaluate_javascript("window.aiPanel.dispatch(" + json.dumps(obj) + ")")`; `main.py`: akcja `new-chat` podłączona; konfiguracja czytana przy starcie z `AI_PANEL_CONFIG`/XDG; zmienna `AI_PANEL_DEFAULT_AGENT` nadpisuje `default_agent` (dla testów i UAT).
- Done when:
  - `make test` → kod 0
- Tests: unit z `FakeBackend` (skrypt zdarzeń) i listą jako `UiSink`: kolejność dispatchy dla tury; `send` podczas trwającej tury odrzucony; `cancel` wywołuje `backend.cancel`; Error backendu → `error` w UI i możliwość kolejnej tury; brak agentów → `init.agents == []`; `new_chat` → nowe `new_session`; bridge: wiadomość bez `type` ignorowana; `json.dumps` z `</script>` i `\u2028` bezpieczne.

### S3-T4: Akcje debug, polityka linków, motyw i test E2E okna
- Status: [x]
- Depends on: S3-T3
- Requirements: FR-8, FR-13, FR-14
- Scope: akcje `debug-send`, `debug-click`, `debug-dump` rejestrowane tylko przy `AI_PANEL_DEBUG=1` (PLAN §12.1), zrzut stanu UI zbierany w JS (`dump`) i zapisywany przez Pythona; CLI `ui-dump`; `window.py`: `decide-policy` – nawigacja głównej ramki tylko do `app/ui/index.html`, linki (`data-external` i każde inne) → `Gtk.UriLauncher`/`Gio.AppInfo.launch_default_for_uri` (tylko `http`, `https`, `mailto`), nowe okna blokowane, menu kontekstowe bez „Reload"/„Inspect" poza debug; motyw: `Adw.StyleManager.dark` + `chat.theme` → `init.theme` i aktualizacja przy zmianie; `chat.font_size` → zmienna CSS. Test GUI e2e.
- Done when:
  - z `make run-headless` i `AI_PANEL_CONFIG` na `tests/data/config_fake.toml` (domyślny `fake-echo`): `gapplication action pl.local.AiPanel debug-send "'md: tabela'"`, po 2 s `make cli ARGS="ui-dump"` → JSON z ostatnią wiadomością asystenta, której `html` zawiera `<table`
  - bez `AI_PANEL_DEBUG` akcja `debug-send` nie istnieje (`gapplication list-actions pl.local.AiPanel` jej nie wypisuje)
  - `make test` → kod 0
- Tests: integracja GUI (marker `gui`): pełna tura z fałszywym agentem przez `debug-send` i `debug-dump`; klik w link zewnętrzny (`debug-click a[data-external]`) nie zmienia URI WebView i woła launcher (podmieniony w teście przez zmienną `AI_PANEL_URI_LOG` zapisującą URI do pliku zamiast otwierania przeglądarki); `chat.theme = "dark"` → `debug-dump.theme == "dark"`.

### UAT S3
- UAT-S3-1: Given panel uruchomiony headless z fałszywym agentem When wysyłam prompt Then odpowiedź pojawia się jako sformatowany markdown z tabelą i podświetlonym kodem
  - Verify: `AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml make run-headless && source .run/headless.env && gapplication action pl.local.AiPanel debug-send "'md: pokaż'" && sleep 2 && make -s cli ARGS="ui-dump"` → `messages[-1].html` zawiera `<table` i `class="hljs`, `messages[-1].role == "assistant"`; `make stop`
- UAT-S3-2: Given złośliwa odpowiedź modelu When jest renderowana Then nie wykonuje się żaden skrypt
  - Verify: `npx playwright test tests/ui/render.spec.mjs -g XSS` → passed
- UAT-S3-3: Given trwająca tura When klikam stop Then tura kończy się znacznikiem „Przerwano"
  - Verify: `AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml AI_PANEL_DEFAULT_AGENT=fake-slow make run-headless && source .run/headless.env`; `debug-send "'długo'"`, `sleep 1`, `gapplication action pl.local.AiPanel debug-click "'#stop'"`, `sleep 2`, `make -s cli ARGS="ui-dump"` → ostatnia wiadomość zawiera „Przerwano"
- UAT-S3-4: Given odpowiedź z linkiem When klikam link Then panel nie nawiguje, a URI trafia do przeglądarki
  - Verify: `AI_PANEL_URI_LOG=$PWD/.run/uri.log` przy `make run-headless`; `debug-send "'md: link'"`, `debug-click "'a[data-external]'"`; `cat .run/uri.log` → `https://example.com/`
- UAT-S3-5: Given brak agentów w konfiguracji When pokazuję panel Then widzę ekran „Dodaj agenta"
  - Verify: `AI_PANEL_CONFIG=/nonexistent make run-headless && source .run/headless.env && make -s cli ARGS="ui-dump"` → `"screen": "empty"`

## S4: Pełna obsługa ACP w UI
Value: W panelu widać myślenie agenta i karty narzędzi, użytkownik zatwierdza lub odrzuca prośby o uprawnienia, przerywa turę, dostaje czytelne błędy (brak komendy, awaria, logowanie) i przełącza agentów oraz modele w nagłówku, widząc oznaczenie trybu z narzędziami.

### S4-T1: Bloki myślenia i karty narzędzi
- Status: [x]
- Depends on: S3-T4
- Requirements: FR-9, FR-10
- Scope: controller: mapowanie `ThinkingDelta`/`ToolCall`/`ToolUpdate` na dispatch `thinking_delta`/`tool_call`/`tool_update`; UI: zwijany `<details class="thinking">` (domyślnie zwinięty, podczas strumienia nagłówek „Myśli…"), karta narzędzia (tytuł jako tekst, ikona statusu `pending|in_progress|completed|failed|cancelled`, rozwijane „Wejście" (`raw_input` jako sformatowany JSON przez `textContent`) i „Wynik" (treść tekstowa renderowana przez `renderMarkdown`, diff jako `<pre>`)); aktualizacja karty po `id`.
- Done when:
  - `npx playwright test tests/ui/tools.spec.mjs` → passed
  - headless + `fake-tool`: `debug-send "'x'"` → `ui-dump` ma `messages[-1].tools[0].status == "completed"`
- Tests: Playwright: myślenie w `<details>` bez `open`; `tool_call` + 2× `tool_update` → jedna karta ze statusem `completed`; `raw_input` z `<script>` wyświetlony jako tekst; aktualizacja nieznanego `id` ignorowana. Unit controller: kolejność zdarzeń.

### S4-T2: Okienko zgody
- Status: [x]
- Depends on: S4-T1
- Requirements: FR-11
- Scope: controller: `PermissionRequest` → dispatch `permission_request` (opcje od agenta); odpowiedź `permission {request_id, option_id|null}` → `backend.respond_permission`; prośby kolejkowane (jedno okienko naraz); UI: modal `role="dialog"` `aria-modal="true"` z tytułem narzędzia (jako tekst), rodzajem, pełnym wejściem (komendy/ścieżki w całości), przyciskami z nazw opcji (allow_* jako „Zezwól…", reject_* jako „Odrzuć…" zgodnie z `name` od agenta), fokus na przycisku odrzucenia, Esc = odrzucenie (`reject_once` lub `null`); żadnego automatycznego wyboru; zamknięcie przy `done`/`cancel`.
- Done when:
  - `npx playwright test tests/ui/permission.spec.mjs` → passed
  - headless + `fake-perm`: `debug-send "'zrób'"`, `debug-click "'[data-option-kind=allow_once]'"` → `ui-dump` pokazuje narzędzie `completed`; przy kliknięciu `reject_once` → status `failed` i tekst odmowy od agenta
- Tests: Playwright: modal pojawia się, fokus na odrzuceniu, Esc → `permission` z opcją reject; dwie prośby → druga po zamknięciu pierwszej. Integracja controller+AcpBackend: allow/deny; cancel z otwartą prośbą → agent dostaje `outcome: cancelled`.

### S4-T3: Anulowanie, awarie i czytelne błędy w UI
- Status: [x]
- Depends on: S4-T2
- Requirements: FR-16, FR-17
- Scope: stop w UI → `session/cancel`, natychmiastowe oznaczenie niezakończonych kart jako `cancelled`, `done cancelled` → „Przerwano"; komunikaty błędów w czacie dla `spawn`, `timeout`, `protocol`, `auth` (z listą metod i podpowiedzią „zaloguj się w terminalu, np. polecenie logowania swojego agenta"), `crashed` (kod + zwijane stderr); po `crashed` kolejny prompt restartuje proces i tworzy nową sesję z informacją „Agent został uruchomiony ponownie, poprzedni kontekst utracony"; po przekroczeniu limitu restartów komunikat i blokada do `new-chat`. Teksty w `app/strings.py`.
- Done when:
  - headless z `AI_PANEL_DEFAULT_AGENT=fake-crash-once`: pierwszy `debug-send "'a'"` → `ui-dump` ostatnia wiadomość błędu zawiera `boom`; drugi `debug-send "'b'"` → komunikat o ponownym uruchomieniu i odpowiedź `Echo: b`
  - `make test` → kod 0
- Tests: unit controller dla każdego `Error.kind` → tekst; integracja: crash → restart → kolejna tura (scenariusz `crash-once`: kończy się tylko przy pierwszym prompcie, marker pliku w katalogu `cwd`); cancel z narzędziem `in_progress` → karta `cancelled`.

### S4-T4: Wybór agenta i modelu, oznaczenie trybu
- Status: [x]
- Depends on: S4-T3
- Requirements: FR-12, FR-28
- Scope: nagłówek UI: lista agentów (`select#agent`), wybór modelu (`select#model`) widoczny tylko gdy backend dał `ConfigOptions` z `category == "model"` (wartości `select`, także grupy); zmiana → `set_option` → `session/set_config_option`, odpowiedź aktualizuje UI; zmiana agenta → nowa rozmowa; plakietka `#mode-badge`: „Agent z narzędziami" (acp) / „Czysty czat" (api) z innym kolorem; akcje D-Bus `agent` (s, stan s) i `agents` (stan `a(ss)`), aktualizowane przy zmianie konfiguracji/wyboru (PLAN §12.1).
- Done when:
  - headless z `config_fake.toml`: `gapplication action pl.local.AiPanel agent "'fake-models'"` → `gdbus call … org.gtk.Actions.Describe agent` zawiera `fake-models`; `ui-dump` → `agent == "fake-models"`, `badge == "tools"`
  - `gdbus call --session -d pl.local.AiPanel -o /pl/local/AiPanel -m org.gtk.Actions.Describe agents` → zawiera `('fake-echo',`
  - `npx playwright test tests/ui/header.spec.mjs` → passed
- Tests: Playwright: brak `config_options` → `#model` ukryty; z opcjami (także grupowanymi) → widoczny, zmiana → mostek `set_option`; zmiana agenta → `select_agent`; plakietka zależna od typu. Integracja: `fake-models` – `session/set_config_option` wysłane, `currentValue` zaktualizowany.

### UAT S4
- UAT-S4-1: Given agent proszący o zgodę When zatwierdzam w okienku Then narzędzie kończy się sukcesem; When odrzucam Then narzędzie nie wykonuje się
  - Verify: `AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml AI_PANEL_DEFAULT_AGENT=fake-perm make run-headless && source .run/headless.env`; `debug-send "'zrób'"`, `sleep 1`, `ui-dump` → `permission_dialog.open == true`; `debug-click "'[data-option-kind=allow_once]'"`, `sleep 1`, `ui-dump` → `tools[0].status == "completed"`; nowa rozmowa (`gapplication action pl.local.AiPanel new-chat`), powtórzyć z `reject_once` → `tools[0].status == "failed"`
- UAT-S4-2: Given agent myślący i używający narzędzi When wysyłam prompt Then widzę zwinięty blok myślenia i kartę narzędzia
  - Verify: `AI_PANEL_DEFAULT_AGENT=fake-tool` przy `make run-headless` (scenariusz `tool` wysyła też myślenie): `debug-send "'x'"`, `ui-dump` → `messages[-1].thinking` niepusty, `tools[0].title` niepusty
- UAT-S4-3: Given agent, który pada When wysyłam prompt dwa razy Then najpierw widzę błąd z `boom`, potem odpowiedź po restarcie
  - Verify: `AI_PANEL_DEFAULT_AGENT=fake-crash-once` przy `make run-headless`: dwa `debug-send`, `ui-dump` → wiadomość błędu zawiera `boom`, kolejna asystenta zawiera `Echo:`
- UAT-S4-4: Given kilku agentów When przełączam agenta przez D-Bus Then nagłówek i plakietka się zmieniają, a lista agentów jest dostępna dla rozszerzenia
  - Verify: `gapplication action pl.local.AiPanel agent "'fake-models'"`; `ui-dump` → `agent == "fake-models"`; `gdbus call … Describe agents` → lista par

## S5: Rozszerzenie GNOME – podstawy
Value: Skrót klawiszowy pokazuje i chowa panel przyklejony do wybranej krawędzi wybranego monitora, na całą wysokość obszaru roboczego, o zadanej szerokości, na wszystkich pulpitach, na wierzchu i poza Alt+Tab/przeglądem; jeśli aplikacja nie działa, rozszerzenie ją uruchamia.

### S5-T1: Szkielet rozszerzenia, schemat GSettings i czysta logika
- Status: [ ]
- Depends on: S1-T1
- Requirements: FR-36, FR-37, FR-45
- Scope: `extension/metadata.json` (uuid `gnome-ai-panel@pl.local`, `shell-version` 45–50, `settings-schema`), `extension/schemas/org.gnome.shell.extensions.gnome-ai-panel.gschema.xml` (wszystkie klucze z PLAN §12.5, `shortcut` domyślnie `['<Super>i']`), `extension/extension.js` z pustymi `enable()`/`disable()`, `extension/lib/geometry.js` (`parseWidth("480"|"30%") -> {px|percent}` z błędem dla złego formatu, `computeRect({side, width, minWidth, maxWidth, workArea}) -> {x,y,width,height}` z clampem, gdy `min > max` wygrywa `min`), `extension/lib/monitor.js` (`pickMonitor(setting, {primary, pointer, count}) -> index`, zły numer → primary); testy gjs; `make build` pakuje zip.
- Done when:
  - `make build` → istnieje `dist/gnome-ai-panel@pl.local.shell-extension.zip`, `unzip -l` pokazuje `lib/geometry.js` i `schemas/gschemas.compiled`
  - `make test-gjs` → passed; `make lint` → kod 0
  - `grep -A1 '<key name="shortcut"' extension/schemas/org.gnome.shell.extensions.gnome-ai-panel.gschema.xml` → `<default>['<Super>i']</default>`
  - Weryfikacja konfliktu skrótu na tej maszynie: `for s in org.gnome.desktop.wm.keybindings org.gnome.shell.keybindings org.gnome.settings-daemon.plugins.media-keys org.gnome.mutter.keybindings; do gsettings list-recursively "$s"; done | grep -i "'<super>i'"` → brak wyników (kod 1). Jeśli `<Super>i` jest zajęty: ustaw domyślnie `['<Super><Shift>a']` w schemacie, PLAN.md (Q5, §12.5) i README, a wynik (który klucz zajmuje `<Super>i`) zapisz w Q5 PLAN.md. Stan z 2026-11-10: `<Super>i` wolny.
- Tests: gjs: `480` → 480 px; `30%` przy 4096 → 1229 (zaokrąglenie w dół); clamp do 320/900; `abc`, `-5`, `120%` → błąd/wartość domyślna 480 z ostrzeżeniem; strona `left` → `x == workArea.x`, `right` → `x + width == workArea.x + workArea.width`; `height == workArea.height`, `y == workArea.y`; monitor `primary`/`pointer`/`1`/`7` (poza zakresem).

### S5-T2: Skrót, uruchamianie aplikacji i pozycjonowanie
- Status: [ ]
- Depends on: S5-T1, S1-T3
- Requirements: FR-34, FR-35, FR-36, FR-37, FR-48
- Scope: `extension/lib/appProxy.js` (`Gio.DBusActionGroup.get(session, "pl.local.AiPanel", "/pl/local/AiPanel")`, `activate(name)`, sprawdzenie właściciela nazwy przez `NameHasOwner`; brak → `Gio.DesktopAppInfo.new("pl.local.AiPanel.desktop").launch` i ponowienie `show` po pojawieniu się nazwy), `extension.js`: `Main.wm.addKeybinding("shortcut", settings, Meta.KeyBindingFlags.NONE, Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW, toggle)`, ostrzeżenie w logu, gdy rejestracja zwróci `Meta.KeyBindingAction.NONE`; śledzenie okna przez `global.display` `window-created` i `get_gtk_application_id() == "pl.local.AiPanel"` (zapas: `get_wm_class()`), przy `shown` i `size-changed` → `move_resize_frame(false, rect)` z `computeRect` dla wybranego monitora, `Main.activateWindow`; `data/pl.local.AiPanel.desktop` (`Exec=gnome-ai-panel --background`, `DBusActivatable=false`, `NoDisplay=false`), `data/pl.local.AiPanel.svg`; `scripts/install.sh` w wersji podstawowej (kopiuje kod i `.desktop`, `gnome-extensions install --force`), cel `make install`.
- Done when:
  - `make build && make lint && make test` → kod 0
  - `make install` → `gnome-extensions list | grep gnome-ai-panel@pl.local` zwraca linię; `test -x ~/.local/bin/gnome-ai-panel`
- Tests: gjs unit `appProxy` z atrapą D-Bus (gdy brak właściciela → wywołany launcher, potem `show`); pozostałe zachowanie sprawdza S5-T4 (e2e).

### S5-T3: Na wierzchu, wszystkie pulpity, poza Alt+Tab i przeglądem; interfejs debug
- Status: [ ]
- Depends on: S5-T2
- Requirements: FR-38
- Scope: dla okna panelu: `make_above()`, `stick()`; `InjectionManager` (`resource:///org/gnome/shell/extensions/extension.js`) nadpisuje filtr okien Alt+Tab (`altTab.js` – listy okien przełączników) i przeglądu (`workspace.js` / `windowPreview` – pomijanie okna), cofane w `disable()`; ustawianie stanu `side` i `collapse-on-escape` w aplikacji przez `org.gtk.Actions.SetState`; eksport interfejsu debug D-Bus z PLAN §12.4 (`Toggle`, `GetState`, `SimulateClick` gated kluczem `debug`); `disable()` zwalnia skrót, sygnały, wstrzyknięcia i interfejs.
- Done when:
  - `make build && make lint && make test` → kod 0
  - weryfikacja zachowania w S5-T4 (`GetState` zwraca `sticky`, `above`, `skipTaskbar` = true)
- Tests: gjs unit funkcji filtrującej `isPanelWindow(win)` z atrapami okien (app id, wm_class, inne okno). Zachowanie w e2e.

### S5-T4: E2E rozszerzenia w gnome-shell --headless
- Status: [ ]
- Depends on: S5-T3
- Requirements: FR-35, FR-36, FR-37, FR-38
- Scope: `scripts/shell-e2e.sh` (zgodnie z sekcją Commands: izolowany `HOME`/`XDG_*` w `.run/shell-home`, `dconf` piszący tylko tam, rozszerzenie rozpakowane do `$XDG_DATA_HOME/gnome-shell/extensions`, `enabled-extensions` ustawione przed startem, `gnome-shell --headless --wayland --no-x11 --virtual-monitor 1920x1080`, aplikacja startowana przez rozszerzenie lub ręcznie z `WAYLAND_DISPLAY` headless shella i `AI_PANEL_DEBUG=1`, sprzątanie przez `trap`); `tests/e2e/conftest.py` (fikstury: wywołanie `gdbus call … GnomeAiPanel.GetState`, `gsettings` z izolowanym środowiskiem); `tests/e2e/test_shell.py`; cel `make test-shell`. Jeśli headless shell nie startuje w ≤ 30 s, skrypt kończy się kodem 3 z komunikatem „gnome-shell headless niedostępny" (rozróżnialne od porażki testów).
- Done when:
  - `make test-shell` → kod 0
- Tests: e2e: `Toggle()` → `visible` true i `rect == [1920-480, panelTop, 480, 1080-panelTop]` (wysokość = obszar roboczy); `gsettings set … side left` + Toggle×2 → `rect[0] == 0`; `width "25%"` → 480; `width "2000"` → 900 (max); `sticky`, `above`, `skipTaskbar` = true; drugi `Toggle()` → `visible` false; po `quit` aplikacji `Toggle()` uruchamia ją ponownie (≤ 10 s).

### UAT S5
- UAT-S5-1: Given headless gnome-shell z rozszerzeniem When uruchamiam zestaw e2e Then panel jest po prawej, na całą wysokość obszaru roboczego, szerokość 480 px
  - Verify: `make test-shell; echo $?` → `0`
- UAT-S5-2: Given ustawienie `side=left`, `width=30%` When przełączam panel Then prostokąt okna zaczyna się od x=0 i ma 30% szerokości monitora
  - Verify: część `make test-shell` (`test_side_left`, `test_width_percent`) → passed; wynik w `.run/shell-e2e.log`
- UAT-S5-3: Given brak działającej aplikacji When wywołuję Toggle rozszerzenia Then aplikacja startuje i panel się pokazuje
  - Verify: `test_launch_when_not_running` w `make test-shell` → passed
- UAT-S5-4: Given zainstalowane rozszerzenie na prawdziwej sesji (po wylogowaniu i zalogowaniu) When naciskam domyślny skrót `Super+I` Then panel wysuwa się przy prawej krawędzi i nie ma go w Alt+Tab `[manual]`
  - Verify: `make install`; wylogowanie/logowanie; `gnome-extensions enable gnome-ai-panel@pl.local`; `gsettings --schemadir ~/.local/share/gnome-shell/extensions/gnome-ai-panel@pl.local/schemas get org.gnome.shell.extensions.gnome-ai-panel shortcut` → `['<Super>i']` (lub `['<Super><Shift>a']`, jeśli S5-T1 wykrył konflikt); naciśnięcie `Super+I`; Alt+Tab nie pokazuje panelu; `gdbus call --session -d org.gnome.Shell -o /org/gnome/Shell/Extensions/GnomeAiPanel -m org.gnome.Shell.Extensions.GnomeAiPanel.GetState` → `"visible": true`

## S6: Rozszerzenie GNOME – interakcja
Value: Ikona w górnym pasku pokazuje/chowa panel i daje menu (nowa rozmowa, wybór agenta, ustawienia, zakończ); panel zwija się po kliknięciu obok, utracie fokusu lub Esc, chyba że jest przypięty; wsuwa się z animacją; szerokość zmienia się przeciąganiem krawędzi; ustawienia rozszerzenia działają na żywo.

### S6-T1: Ikona w pasku z menu
- Status: [ ]
- Depends on: S5-T3, S4-T4
- Requirements: FR-39
- Scope: `PanelMenu.Button` dodany przez `Main.panel.addToStatusArea("gnome-ai-panel", …)`, ikona `St.Icon` (symboliczna z `data/` w paczce rozszerzenia lub `dialog-information-symbolic` jako zapas); lewy klik → toggle (bez otwierania menu), prawy klik → menu: „Nowa rozmowa" (`new-chat` + `show`), podmenu „Agent" z pozycjami ze stanu akcji `agents` i zaznaczeniem bieżącego `agent` (odświeżane sygnałem `Changed`), „Ustawienia panelu" (`this.openPreferences()`), „Ustawienia agentów" (akcja aplikacji `preferences`; w tym etapie otwiera `config.toml` domyślnym programem, plik tworzony z komentarzem nagłówkowym i `0600`, jeśli nie istnieje), „Zakończ" (`quit`); `show-tray-icon` false → przycisk usunięty, na żywo. `GetState.trayIcon` odzwierciedla stan.
- Done when:
  - `make test-shell` → kod 0 (nowe testy menu przechodzą)
  - `make lint && make test` → kod 0
- Tests: gjs unit `buildAgentMenuModel(agentsState, current)`; e2e: `GetState.trayIcon == true`, po `gsettings set … show-tray-icon false` → false; metoda debug `ActivateMenuItem(id)` (tylko przy `debug`) dla „Nowa rozmowa” → aplikacja widoczna i pusta rozmowa (`ui-dump`).

### S6-T2: Zwijanie (klik obok, fokus, Esc) i przypinanie
- Status: [ ]
- Depends on: S6-T1
- Requirements: FR-40, FR-41
- Scope: `extension/lib/collapse.js`: `shouldCollapse({event: "click"|"focus"|"escape", point, panelRect, trayRect, pinned, settings}) -> bool` (klik w ikonę paska nigdy nie zwija; przypięty nigdy nie zwija); `extension.js`: gdy panel widoczny – `global.stage.connect("captured-event")` dla `BUTTON_PRESS`/`TOUCH_BEGIN`, zwraca `Clutter.EVENT_PROPAGATE` (zdarzenie trafia dalej), odłączane po schowaniu; `notify::focus-window` gdy `collapse-on-focus-loss`; chowanie przez akcję `hide`. Aplikacja: przycisk „Przypnij" w nagłówku (`#pin`, `aria-pressed`) → stan akcji `pinned`; Esc w stronie (gdy brak modalu) → wiadomość `escape` → `hide`, jeśli stan `collapse-on-escape` true i nie przypięty. Rozszerzenie obserwuje `pinned` przez `Changed`.
- Done when:
  - `make test-gjs` → passed; `make test-shell` → passed; `make test` → kod 0
- Tests: gjs: tablica przypadków `shouldCollapse` (w środku/poza/na ikonie/przypięty/wyłączone ustawienie); Playwright: Esc bez modalu → `escape`, z modalem zgody → odrzucenie zgody, brak `escape`; klik `#pin` → `pin {value:true}`; GUI: wiadomość `escape` przy `pinned=false` → `visible=false`; e2e: `SimulateClick(10,500)` przy panelu po prawej → `visible` false; po `SetState pinned true` → zostaje widoczny; klik wewnątrz panelu → zostaje.

### S6-T3: Animacja i zmiana szerokości przeciąganiem
- Status: [ ]
- Depends on: S6-T2
- Requirements: FR-42, FR-43
- Scope: animacja: przy pokazaniu aktor okna startuje przesunięty o szerokość poza krawędź i `ease({translation_x: 0, duration: animation-ms, mode: Clutter.AnimationMode.EASE_OUT_QUAD})`; przy chowaniu odwrotnie, potem `hide`; `animation-ms == 0` → bez animacji; ponowne przełączenie w trakcie animacji przerywa ją bez migotania (`remove_all_transitions`). Resize: w aplikacji 6-px `Gtk.Box` uchwyt po wewnętrznej stronie (zależnie od stanu `side`), kursor `ew-resize`, `Gtk.GestureClick` → `Gdk.Toplevel.begin_resize(edge, device, button, x, y, time)`; rozszerzenie na `size-changed` (gdy panel widoczny i nie w trakcie własnego `move_resize_frame`) clampuje do min/max, zapisuje `width` jako px i ponownie przykleja do krawędzi.
- Done when:
  - `make test-shell` → passed; `make test` → kod 0
- Tests: gjs: `widthFromResize(newWidth, min, max) -> "NNN"`, `animationStartX(side, width)`; e2e: `gsettings set … animation-ms 0` → po `Toggle()` `GetState.visible` true w ≤ 100 ms; metoda debug `SimulateResize(600)` (woła `move_resize_frame` jak użytkownik) → `gsettings get … width` == `'600'`; `SimulateResize(5000)` → `'900'`; GUI: uchwyt jest po lewej przy `side=right` (`debug-dump.handle_side == "left"`).

### S6-T4: Okno ustawień rozszerzenia i ustawienia na żywo
- Status: [ ]
- Depends on: S6-T3
- Requirements: FR-44, FR-34
- Scope: `extension/prefs.js` (`ExtensionPreferences.fillPreferencesWindow`, Adw): strona „Układ" (strona: `Adw.ComboRow` lewa/prawa; szerokość: `Adw.EntryRow` z walidacją `parseWidth` i komunikatem błędu; min/max: `Adw.SpinRow`; monitor: główny / pod kursorem / lista monitorów z `Gdk.Display.get_monitors()`), „Zachowanie" (skrót: `Adw.EntryRow` z walidacją `Gtk.accelerator_parse`, przycisk „Wyczyść"; ikona w pasku; trzy przełączniki zwijania; czas animacji `Adw.SpinRow` 0–1000); wszystko przez `settings.bind`; `extension.js` reaguje na `changed::` każdego klucza: ponowne pozycjonowanie, ponowna rejestracja skrótu, ikona, przekazanie `side`/`collapse-on-escape` do aplikacji – bez przeładowania rozszerzenia.
- Done when:
  - `gjs -m tests/gjs/prefs_smoke.js` (ładuje `prefs.js` z atrapą `ExtensionPreferences` pod Xvfb lub pomija przy braku wyświetlacza) → kod 0
  - `make test-shell` → passed (testy na żywo); `make lint && make test` → kod 0
- Tests: gjs: walidatory skrótu i szerokości; e2e: przy widocznym panelu `gsettings set … width 600` → `rect[2] == 600` w ≤ 1 s bez Toggle; `side left` → `rect[0] == 0`; `shortcut "['<Super>F12']"` → `GetState.keybinding` zawiera `<Super>F12`.

### UAT S6
- UAT-S6-1: Given widoczny, nieprzypięty panel When klikam poza nim Then panel się chowa; Given przypięty When klikam poza nim Then zostaje
  - Verify: `make test-shell` → `test_click_outside_collapses` i `test_pinned_stays` passed
- UAT-S6-2: Given ustawienia rozszerzenia When zmieniam szerokość i stronę przez `gsettings` przy widocznym panelu Then panel od razu zmienia położenie
  - Verify: `make test-shell` → `test_live_width`, `test_live_side` passed
- UAT-S6-3: Given przeciągnięcie krawędzi do 5000 px When kończę zmianę Then szerokość zapisuje się jako 900 (max)
  - Verify: `make test-shell` → `test_resize_clamped` passed
- UAT-S6-4: Given ikona w pasku When wyłączam `show-tray-icon` Then ikona znika bez przeładowania
  - Verify: `make test-shell` → `test_tray_toggle` passed
- UAT-S6-5: Given prawdziwa sesja When klikam ikonę, wybieram agenta z menu, otwieram „Ustawienia panelu" i oglądam animację Then wszystko działa płynnie, a klik w ikonę przy otwartym panelu chowa go (nie zwija i rozwija) `[manual]`
  - Verify: `make install`, ponowne logowanie, `gnome-extensions prefs gnome-ai-panel@pl.local`; obserwacja

## S7: Czysty czat przez API
Value: Użytkownik dodaje agenta `type = "api"` (np. API Anthropic z kluczem w keyringu) i prowadzi szybki czat bez narzędzi i bez dostępu do plików, z wyborem modelu i promptem systemowym.

### S7-T1: ApiBackend
- Status: [ ]
- Depends on: S2-T2, S2-T3
- Requirements: FR-19
- Scope: `app/backends/api.py`: `httpx.AsyncClient.stream("POST", endpoint, json={model, max_tokens, system?, messages, stream: true}, headers={x-api-key, anthropic-version, content-type})`; parser SSE (`event:`/`data:`, wieloliniowe `data`, komentarze `:`), mapowanie `content_block_delta` `text_delta` → TextDelta, `thinking_delta` → ThinkingDelta, `message_delta.usage` → Usage, `message_stop` → Done(`stop_reason` z `message_delta`), `error` → Error(kind `http`); historia rozmowy per sesja w pamięci (user/assistant), anulowanie = zamknięcie strumienia + Done `cancelled` (częściowa odpowiedź zapisana w historii); błędy: 401 → „Nieprawidłowy klucz API", 429 → „Limit zapytań", 5xx/529 → „Usługa przeciążona", błąd sieci → „Brak połączenia z <host>"; klucz nigdy w logu (redakcja nagłówka). `tests/fakes/fake_anthropic.py` (stdlib `http.server`, tryby z PLAN „Commands"; zapisuje ostatnie żądanie do pliku z `--record`).
- Done when:
  - `make test` → kod 0
- Tests: unit parsera SSE (podział na granicach pakietów, CRLF, wieloliniowe `data`); integracja z fałszywym serwerem: tekst, myślenie, 401, 429, wolny strumień + cancel ≤ 1 s, druga tura wysyła historię (2 wiadomości user + 1 assistant w `--record`), `system` z `system_prompt`, nagłówek `anthropic-version` z konfiguracji, klucz nieobecny w logu.

### S7-T2: Agent API w panelu i CLI
- Status: [ ]
- Depends on: S7-T1, S4-T4
- Requirements: FR-19, FR-12, FR-28, FR-25
- Scope: `get_backend` obsługuje `type="api"`; wybór modelu w nagłówku z listy `models` (controller emituje syntetyczne `config_options` z `category: "model"`), zmiana modelu dotyczy kolejnych tur; plakietka „Czysty czat"; `test_agent` dla api: minimalne żądanie `max_tokens: 1` (`ping`) i informacja o zużyciu tokenów; CLI `chat`/`test-agent` dla api; testy generują w `tmp_path` plik konfiguracji z agentem `fake-api`, którego `endpoint` wskazuje port fałszywego serwera (`http://127.0.0.1:<PORT>/v1/messages`).
- Done when:
  - integracja: `make cli ARGS="chat fake-api 'Cześć'"` z wygenerowaną konfiguracją → stdout zawiera tekst z fałszywego serwera, kod 0
  - `make test` → kod 0
- Tests: integracja CLI i GUI (headless): `ui-dump.badge == "chat"`, model z listy wysłany w żądaniu po zmianie `set_option`; `test-agent` z kluczem `sk-test-401` → kod 2 i „Nieprawidłowy klucz API".

### UAT S7
- UAT-S7-1: Given fałszywy serwer API i agent `type="api"` When czatuję z terminala Then dostaję strumień odpowiedzi
  - Verify: `.venv/bin/python tests/fakes/fake_anthropic.py --port 8765 & sleep 1`; plik `/tmp/api.toml` z `[agents.api] type="api" endpoint="http://127.0.0.1:8765/v1/messages" model="m1" models=["m1","m2"] api_key={source="literal", value="sk-test-ok"}`; `AI_PANEL_CONFIG=/tmp/api.toml make cli ARGS="chat api 'Cześć'"` → tekst odpowiedzi, kod 0; `kill %1`
- UAT-S7-2: Given zły klucz When `test-agent` Then czytelny komunikat i kod 2
  - Verify: jak wyżej z `value="sk-test-401"`; `make cli ARGS="test-agent api"; echo $?` → „Nieprawidłowy klucz API", `2`
- UAT-S7-3: Given agent API w panelu When pokazuję panel Then plakietka mówi „Czysty czat" i są dwa modele do wyboru
  - Verify: `AI_PANEL_CONFIG=/tmp/api.toml make run-headless && source .run/headless.env && make -s cli ARGS="ui-dump"` → `badge == "chat"`; `debug-send "'x'"` → odpowiedź w `messages[-1].text`
- UAT-S7-4: Given prawdziwy klucz Anthropic w keyringu When czatuję z agentem z szablonu Claude API Then dostaję odpowiedź `[manual]`
  - Verify: `printf '%s' "$KLUCZ" | make cli ARGS="secret set claude-api-key"`; agent z `endpoint="https://api.anthropic.com/v1/messages"`, `api_key={source="keyring",name="claude-api-key"}`; `make cli ARGS="chat claude 'OK?'"`

## S8: Okno ustawień aplikacji
Value: Użytkownik dodaje, edytuje i usuwa agentów (z szablonów Kiro ACP, Claude ACP, Claude API lub własnego), zarządza sekretami, serwerami MCP i wyglądem czatu oraz testuje połączenie bez ręcznej edycji pliku; ręczne zmiany pliku są widoczne od razu.

### S8-T1: Zapis konfiguracji i przeładowanie na żywo
- Status: [ ]
- Depends on: S4-T4
- Requirements: FR-22
- Scope: `config.py`: `ConfigEditor` (tomlkit) – `upsert_agent`, `delete_agent`, `upsert_mcp`, `delete_mcp`, `set_chat`, `set_default_agent`; zapis atomowy, `0600`, katalog `0700`, komentarze i nieznane klucze zachowane; `app/config_watch.py`: `Gio.FileMonitor` na katalogu (obsługa zapisu przez rename w edytorach), debounce 300 ms, przeładowanie → controller dostaje nową konfigurację (`init` w UI, stany `agents`/`agent`, oznaczenie zmienionych agentów do restartu przy następnej sesji), błąd składni → baner „Błąd w config.toml: …" i zachowanie poprzedniej konfiguracji.
- Done when:
  - headless: dopisanie agenta do pliku `$AI_PANEL_CONFIG` (`cat >> …`) → w ≤ 2 s `gdbus call … Describe agents` zawiera nowe id; zapis niepoprawnego TOML → `ui-dump.banner` zaczyna się od `Błąd w config.toml`
  - `make test` → kod 0
- Tests: unit `ConfigEditor`: komentarz użytkownika przetrwa `upsert_agent`; usunięcie agenta usuwa też `[agents.x.env]`; uprawnienia `0600`; unit debounce (3 zapisy → 1 przeładowanie); GUI: przeładowanie i baner.

### S8-T2: Szablony i strona agentów
- Status: [ ]
- Depends on: S8-T1
- Requirements: FR-24, FR-26
- Scope: `app/templates.py`: szablony jako dane (Kiro ACP: `command="kiro-cli"`, `args=["acp"]`, `cwd="~/.cache/ai-panel"`; Claude ACP: `command="claude-agent-acp"`, `cwd="~/.cache/ai-panel"`, `env.ANTHROPIC_API_KEY={source="keyring", name="anthropic-api-key"}`, `session_meta` z listą wyłączonych narzędzi; Claude API: `endpoint="https://api.anthropic.com/v1/messages"`, `model`, `models`, `api_key` z keyringu; Własny: puste pola) – szablon tylko wypełnia formularz; `app/settings_ui.py`: `Adw.PreferencesDialog`, strona „Agenci": lista (`Adw.ActionRow` na agenta: nazwa, typ, ostrzeżenia walidacji), „Dodaj" (wybór szablonu → formularz), edycja, usuwanie z potwierdzeniem (`Adw.AlertDialog`), „Ustaw jako domyślny"; formularz: id (walidacja `^[a-z0-9-]+$`, unikalność), nazwa, typ, komenda, argumenty (lista wierszy), cwd, timeout, MCP (multi-select z `[mcp.*]`), edytor env (wiersz: nazwa, źródło `Adw.ComboRow`, pola zależne od źródła), pola api; zapis przez `ConfigEditor`. Akcja `preferences` otwiera ten dialog (zamiast pliku z S6-T1); dialog dostępny też z przycisku ⚙ w nagłówku czatu (`open_settings`).
- Done when:
  - `make test` → kod 0 (testy GUI dialogu przechodzą)
  - headless: `gapplication action pl.local.AiPanel preferences` → log `settings opened`, bez błędów w logu
- Tests: unit szablonów (każdy daje konfigurację przechodzącą walidację po uzupełnieniu wymaganych pól; brak efektu bez zapisu); GUI in-process (Xvfb): dodanie agenta z szablonu Kiro → `config.toml` zawiera `[agents.kiro]` z `command = "kiro-cli"`; edycja argumentów; usunięcie; zły id → komunikat i brak zapisu.

### S8-T3: Strony sekretów, MCP i wyglądu
- Status: [ ]
- Depends on: S8-T2
- Requirements: FR-26, FR-27, FR-46
- Scope: strona „Sekrety": lista nazw keyring używanych w konfiguracji ze stanem „ustawiony/brak" (`SecretStore.has`), „Ustaw" (`Adw.PasswordEntryRow`, wartość nigdy nie jest odczytywana z powrotem do UI), „Usuń"; ostrzeżenie (ikona + tekst) przy każdym `literal` w zmiennej o nazwie sekretnej, w formularzu agenta i na liście; strona „Serwery MCP": dodaj/edytuj/usuń `[mcp.*]` (komenda, argumenty, env), ostrzeżenie przy usuwaniu serwera używanego przez agenta; strona „Wygląd": `font_size` (`Adw.SpinRow` 10–24), `theme` (system/jasny/ciemny), `history_dir` (wybór katalogu `Gtk.FileDialog`); zmiany wyglądu działają natychmiast przez hot reload.
- Done when:
  - `make test` → kod 0
- Tests: GUI z `MemoryStore`: ustawienie sekretu → `has` true, wartość nie występuje w żadnym widżecie po ponownym otwarciu ani w `config.toml`; literal z `API_KEY` → widoczne ostrzeżenie; dodanie MCP i przypisanie do agenta → `mcp = ["gnome"]` w pliku i przekazanie w `session/new` (fałszywy agent `--record`); zmiana `font_size` → `ui-dump` ma nowy rozmiar.

### S8-T4: „Test połączenia" i ekran startowy „Dodaj agenta"
- Status: [ ]
- Depends on: S8-T3
- Requirements: FR-25, FR-23, FR-24
- Scope: przycisk „Test połączenia" w formularzu agenta (testuje bieżące, niezapisane wartości przez `diagnostics.test_agent`), spinner, wynik (`Adw.ActionRow` z nazwą/wersją agenta, protokołem, metodami logowania) lub czytelny błąd; anulowanie testu przy zamknięciu formularza; ekran pusty w czacie ma przycisk „Dodaj agenta" (`open_settings` z `{page:"agents", add:true}`) otwierający wybór szablonu.
- Done when:
  - `make test` → kod 0
  - headless z pustą konfiguracją: `gapplication action pl.local.AiPanel debug-click "'#empty-state button'"` → log `settings opened page=agents add=true`
- Tests: GUI: test na fałszywym agencie `echo` → wiersz wyniku zawiera nazwę agenta; na `missing` → komunikat „Nie znaleziono polecenia"; zamknięcie formularza w trakcie testu zabija proces (brak procesu fałszywego agenta po 3 s).

### S8-T5: Pytanie o sekret (`source = "prompt"`) w panelu
- Status: [ ]
- Depends on: S8-T4
- Requirements: FR-21
- Scope: controller dostarcza `prompt_cb` do `resolve_env`: wysyła `secret_prompt {token, label}` do UI, czeka na `secret_prompt_reply` (timeout 5 min → Error „Nie podano wartości"); UI: modal z polem hasła (`type=password`, `autocomplete=off`), „OK"/„Anuluj"; wartość tylko w pamięci procesu na czas działania aplikacji (cache per agent+zmienna), nigdy w logu, historii ani `debug-dump`.
- Done when:
  - `make test` → kod 0
- Tests: Playwright: modal, Enter = OK, Anuluj → `value:null`; integracja controller z agentem `fake-env` i `source="prompt"`: odpowiedź agenta zawiera podaną wartość; drugi start agenta nie pyta ponownie; wartość nie występuje w `app.log` ani `debug-dump.json`; anulowanie → błąd w czacie, brak startu agenta.

### UAT S8
- UAT-S8-1: Given pusta konfiguracja When dodaję agenta z szablonu przez okno ustawień Then plik `config.toml` zawiera agenta, a panel go pokazuje bez restartu
  - Verify: `xvfb-run -a dbus-run-session -- .venv/bin/pytest -q -k test_add_agent_from_template` → passed
- UAT-S8-2: Given działający panel When ręcznie dopisuję agenta do `config.toml` Then pojawia się w liście agentów w ≤ 2 s; When psuję składnię Then widzę baner błędu, a poprzedni agenci działają
  - Verify: `make run-headless && source .run/headless.env`; `printf '\n[agents.nowy]\ntype="acp"\ncommand="%s"\nargs=["tests/fakes/fake_acp_agent.py","--scenario","echo"]\ncwd="/tmp/aip"\n' "$PWD/.venv/bin/python" >> "$AI_PANEL_CONFIG"`; `sleep 2`; `gdbus call … Describe agents` → zawiera `nowy`; `echo '[[[' >> "$AI_PANEL_CONFIG"; sleep 2; make -s cli ARGS="ui-dump"` → `banner` zaczyna się od `Błąd w config.toml`
- UAT-S8-3: Given sekret `literal` dla `API_KEY` When otwieram listę agentów Then widzę ostrzeżenie; sekret z keyringu nie trafia do pliku
  - Verify: `xvfb-run -a dbus-run-session -- .venv/bin/pytest -q -k "literal_warning or secret_not_in_file"` → passed
- UAT-S8-4: Given okno ustawień na prawdziwej sesji When dodaję agenta Kiro z szablonu i klikam „Test połączenia" Then widzę nazwę i wersję agenta `[manual]`
  - Verify: `make run`, ikona → „Ustawienia agentów" lub `gapplication action pl.local.AiPanel preferences`; obserwacja

## S9: Historia, wiele rozmów, obrazki i zużycie
Value: Rozmowy zapisują się między uruchomieniami; użytkownik widzi listę, wraca do starej rozmowy lub ją usuwa, wkleja obrazki do promptu i widzi zużycie tokenów/kosztu.

### S9-T1: Zapis historii
- Status: [ ]
- Depends on: S8-T1
- Requirements: FR-30
- Scope: `app/storage.py` (format z PLAN §11.3): `save(conv)` atomowo z `0600` (katalog `0700`), `list() -> [summary]` posortowane po `updated` malejąco, `load(id)`, `delete(id)`; uszkodzony plik pomijany z ostrzeżeniem w logu; controller zapisuje po każdej zakończonej turze (także `cancelled` i po błędzie) z `acp_session_id`; tytuł = pierwsze 60 znaków pierwszego promptu; sekrety z `prompt` nie trafiają do historii; CLI `history list [--json]`, `history show ID`.
- Done when:
  - po turze w headless: `make -s cli ARGS="history list --json"` → 1 wpis z `title` równym promptowi
  - `make test` → kod 0
- Tests: unit: zapis/odczyt/usuwanie, atomowość (przerwany zapis nie psuje poprzedniego pliku – symulacja wyjątku przed `os.replace`), uszkodzony JSON pomijany, uprawnienia, sortowanie; integracja: tura → plik w `history_dir`.

### S9-T2: Lista rozmów i powrót do rozmowy
- Status: [ ]
- Depends on: S9-T1
- Requirements: FR-31
- Scope: UI: przycisk „Historia" w nagłówku → ekran listy (`history_list`), pozycja: tytuł, agent, data; „Otwórz" (`history_open`), „Usuń" z potwierdzeniem, „Nowa rozmowa"; puste: „Brak zapisanych rozmów"; controller: otwarcie wyświetla transkrypt (`conversation`); kolejny prompt: agent ACP z `loadSession` → `session/load` z `acp_session_id` (powtórki `session/update` w trakcie load nie są ponownie dopisywane do transkryptu), bez → nowa sesja + informacja „Agent nie pamięta wcześniejszego kontekstu"; agent API → historia wiadomości z pliku wysyłana w żądaniu; agent usunięty z konfiguracji → transkrypt tylko do odczytu z informacją.
- Done when:
  - headless: dwie rozmowy (`debug-send`, `new-chat`, `debug-send`), `debug-click "'#history-button'"`, `ui-dump` → `screen == "history"` i 2 pozycje
  - `make test` → kod 0
- Tests: Playwright: lista, puste, usuwanie z potwierdzeniem; integracja: `fake-load` dostaje `session/load` z właściwym id; `fake-echo` (bez loadSession) → nowa sesja + komunikat; API → `--record` zawiera poprzednie wiadomości.

### S9-T3: Wklejanie obrazków
- Status: [ ]
- Depends on: S9-T2
- Requirements: FR-32
- Scope: UI: `paste` z `image/*` (oraz przeciągnij-upuść) → miniatury nad polem z „×", limit 5 MB na obraz i 4 obrazy (komunikat przy przekroczeniu), `send {text, images:[{mimeType, data}]}`; controller: ACP – blok `image` tylko gdy `promptCapabilities.image`, inaczej komunikat „Ten agent nie przyjmuje obrazków" i brak wysłania; API – blok `{"type":"image","source":{"type":"base64",…}}`; historia zapisuje obrazy jako części (base64) – przy > 20 MB na rozmowę zapisuje tylko znacznik „[obraz pominięty]".
- Done when:
  - `npx playwright test tests/ui/images.spec.mjs` → passed; `make test` → kod 0
- Tests: Playwright: wklejenie syntetycznego PNG (`ClipboardEvent` z `DataTransfer`) → miniatura i `send` z `images`; za duży plik → komunikat. Integracja: `fake-image` odpowiada „obraz 1x1 image/png”; `fake-echo` (bez image) → komunikat i brak `session/prompt`; API → `--record` zawiera blok image.

### S9-T4: Zużycie tokenów i kosztu
- Status: [ ]
- Depends on: S9-T2
- Requirements: FR-33
- Scope: controller: `Usage` (ACP `usage_update`, API `message_start.usage` + `message_delta.usage`) → dispatch `usage`; UI: w stopce dyskretny wskaźnik „kontekst 53k/200k · 0,05 USD" (ACP) lub „wejście/wyjście tokenów" (API); brak danych → wskaźnik ukryty; wartość zapisywana w historii rozmowy.
- Done when:
  - headless z `fake-usage`: po turze `ui-dump.usage` zawiera `used` i `size`
  - `make test` → kod 0
- Tests: Playwright: formatowanie liczb (53000 → „53k", przecinek dziesiętny); unit mapowania z obu backendów; brak `usage` → ukryty.

### UAT S9
- UAT-S9-1: Given rozmowa zakończona i aplikacja zrestartowana When otwieram historię Then rozmowa jest na liście i mogę ją otworzyć
  - Verify: headless: `debug-send "'Pierwsza rozmowa'"`, `sleep 2`, `make stop`, `make run-headless` (ten sam `.run/home`), `make -s cli ARGS="history list --json"` → wpis z tytułem `Pierwsza rozmowa`; `debug-click "'#history-button'"`, `debug-click "'[data-history-open]'"`, `ui-dump` → `messages[0].text == "Pierwsza rozmowa"`
- UAT-S9-2: Given agent wspierający `loadSession` When kontynuuję starą rozmowę Then agent dostaje `session/load`
  - Verify: `xvfb-run -a dbus-run-session -- .venv/bin/pytest -q -k test_resume_with_load_session` → passed
- UAT-S9-3: Given agent przyjmujący obrazy When wklejam obraz Then agent go otrzymuje
  - Verify: `npx playwright test tests/ui/images.spec.mjs` → passed; `xvfb-run -a dbus-run-session -- .venv/bin/pytest -q -k test_image_prompt` → passed
- UAT-S9-4: Given agent raportujący zużycie When kończy turę Then widzę wskaźnik zużycia
  - Verify: headless z `fake-usage`: `debug-send "'x'"`, `ui-dump` → `usage.used == 53000`

## S10: Instalacja i autostart
Value: Użytkownik instaluje panel jedną komendą bez sudo, panel startuje w tle razem z sesją, a README prowadzi przez konfigurację okrojonych agentów Kiro i Claude.

### S10-T1: Pełny instalator, deinstalator i autostart
- Status: [ ]
- Depends on: S6-T4, S8-T4
- Requirements: FR-48, FR-1
- Scope: `scripts/install.sh` (idempotentny): kopia `app/`, `mcp/`, `data/` do `~/.local/share/gnome-ai-panel/`, venv tam (`--system-site-packages`, `requirements.txt`), launcher `~/.local/bin/gnome-ai-panel`, `.desktop` w `~/.local/share/applications/`, ikona w `~/.local/share/icons/hicolor/scalable/apps/`, rozszerzenie (`gnome-extensions install --force`), opcja `--autostart` → `~/.config/autostart/pl.local.AiPanel.desktop` z `Exec=gnome-ai-panel --background`; komunikat, że na Waylandzie nowe rozszerzenie wymaga ponownego logowania; `scripts/uninstall.sh` usuwa wszystko poza `config.toml`, historią i sekretami (wypisuje, co zostało); cele `make install`, `make uninstall`; ustawienie „Uruchamiaj przy logowaniu” na stronie „Wygląd”/„Ogólne” w ustawieniach aplikacji (tworzy/usuwa plik autostartu).
- Done when:
  - `HOME=$(mktemp -d) make install ARGS=--autostart` (z `XDG_*` wskazującymi na ten katalog) → istnieją launcher, `.desktop`, plik autostartu; ponowne `make install` → kod 0; `make uninstall` → pliki usunięte, `config.toml` zostaje
  - `$HOME/.local/bin/gnome-ai-panel --version` → `0.1.0`
  - `make test` → kod 0
- Tests: integracja w tymczasowym `HOME` (bez `gnome-extensions install`, pomijane gdy `AI_PANEL_SKIP_EXTENSION_INSTALL=1`): lista plików po instalacji i deinstalacji; `--background` nie pokazuje okna (`Describe visible` false).

### S10-T2: Dokumentacja i przykłady okrojonych agentów
- Status: [ ]
- Depends on: S10-T1
- Requirements: FR-50
- Scope: `data/examples/kiro/ai-panel-chat.json` (agent Kiro bez narzędzi zapisu i powłoki – format zweryfikować w dokumentacji Kiro CLI → custom agents) i instrukcja umieszczenia go w `~/.cache/ai-panel/.kiro/agents/` oraz `args = ["acp", "--agent", "ai-panel-chat"]`; `data/examples/config.example.toml` (wszystkie typy, wszystkie źródła sekretów, bez prawdziwych wartości); README: instalacja, domyślny skrót `Super+I` (dlaczego nie `Super+A`: na Ubuntu to „Pokaż aplikacje"; jak zmienić skrót w ustawieniach rozszerzenia lub przez `gsettings … set org.gnome.shell.extensions.gnome-ai-panel shortcut "['<Super><Shift>a']"`), konfiguracja Kiro (logowanie lub `KIRO_API_KEY` ze źródła `keyring`), Claude ACP (`npm install -g @agentclientprotocol/claude-agent-acp`, `session_meta`), Claude API, bezpieczeństwo (§6 spec), rozwiązywanie problemów (logi, `check-config`, `test-agent`), sekcja „Smoke test” dla kroków `[manual]`; `check-config` na pliku przykładowym przechodzi.
- Done when:
  - `make cli ARGS="check-config --config data/examples/config.example.toml"` → kod 0 (ostrzeżenia dozwolone, błędy nie)
  - `python3 -m json.tool data/examples/kiro/ai-panel-chat.json` → kod 0
  - `grep -nE "sk-ant|KIRO_API_KEY=.+" README.md data/examples -r` → brak wyników (kod 1)
- Tests: unit: plik przykładowy parsuje się i przechodzi walidację; test, że README zawiera nagłówki „Instalacja”, „Konfiguracja agentów”, „Bezpieczeństwo”, „Smoke test”.

### UAT S10
- UAT-S10-1: Given czysty katalog domowy When `make install ARGS=--autostart` Then aplikacja, plik .desktop, autostart i rozszerzenie są na miejscu
  - Verify: `export H=$(mktemp -d); HOME=$H XDG_CONFIG_HOME=$H/.config XDG_DATA_HOME=$H/.local/share AI_PANEL_SKIP_EXTENSION_INSTALL=1 make install ARGS=--autostart; ls $H/.local/bin/gnome-ai-panel $H/.config/autostart/pl.local.AiPanel.desktop $H/.local/share/applications/pl.local.AiPanel.desktop` → trzy ścieżki bez błędu
- UAT-S10-2: Given zainstalowana aplikacja When `make uninstall` Then pliki programu znikają, a konfiguracja zostaje
  - Verify: w tym samym `$H`: `make uninstall`; `ls $H/.local/bin/gnome-ai-panel` → błąd; `ls $H/.config/gnome-ai-panel/config.toml` (jeśli istniał) → istnieje
- UAT-S10-3: Given przykładowa konfiguracja When `check-config` Then brak błędów
  - Verify: `make cli ARGS="check-config --config data/examples/config.example.toml"; echo $?` → `0`
- UAT-S10-4: Given instalacja z autostartem na prawdziwej sesji When loguję się ponownie Then aplikacja działa w tle, a skrót od razu pokazuje panel `[manual]`
  - Verify: `make install ARGS=--autostart`; wylogowanie/logowanie; `gdbus call --session -d pl.local.AiPanel -o /pl/local/AiPanel -m org.gtk.Actions.Describe visible` → `false`; skrót → panel

## S11: Serwer MCP „GNOME”
Value: Agenty podpięte do panelu mogą wysłać powiadomienie na pulpit i odczytać schowek, a zapis schowka jest możliwy tylko po jawnym włączeniu i za zgodą użytkownika.

### S11-T1: Serwer MCP z narzędziem powiadomień
- Status: [ ]
- Depends on: S10-T1
- Requirements: FR-47
- Scope: `mcp/gnome_mcp.py` (tylko stdlib + `gi`): MCP po stdio (JSON-RPC linia po linii): `initialize` (wersja protokołu MCP zweryfikowana w specyfikacji MCP, `capabilities.tools`), `notifications/initialized`, `tools/list`, `tools/call`; narzędzie `notify(title, body)` przez `org.freedesktop.Notifications.Notify` (Gio D-Bus), adnotacje `readOnlyHint: false`, `destructiveHint: false`; walidacja argumentów (string, długość ≤ 200/2000) z błędem MCP; launcher `gnome-ai-panel-mcp` instalowany przez `install.sh`; szablon „GNOME MCP” w ustawieniach (strona MCP) wypełnia `command = "gnome-ai-panel-mcp"`.
- Done when:
  - `printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | .venv/bin/python mcp/gnome_mcp.py` → druga odpowiedź zawiera `"name": "notify"`
  - `make test` → kod 0
- Tests: integracja pod `dbus-run-session` z atrapą serwera powiadomień (`python3-dbusmock` nie jest wymagany: prosta usługa Gio w teście rejestruje `org.freedesktop.Notifications` i zapisuje wywołania): `tools/call notify` → wywołanie z tytułem; zły argument → błąd `isError`/JSON-RPC; nieznane narzędzie → błąd.

### S11-T2: Narzędzia schowka przez aplikację panelu
- Status: [ ]
- Depends on: S11-T1
- Requirements: FR-47
- Scope: `app/clipboard_service.py`: obiekt D-Bus `/pl/local/AiPanel/Clipboard` (interfejs `pl.local.AiPanel.Clipboard`: `ReadText() -> s`, `WriteText(s)`) w aplikacji, używa `Gdk.Clipboard` okna (odczyt może wymagać widocznego panelu – wtedy błąd „Pokaż panel, aby odczytać schowek”); `mcp/gnome_mcp.py`: `clipboard_read` (`readOnlyHint: true`), `clipboard_write` widoczne tylko z flagą `--allow-write` (`destructiveHint: true`, opis mówi, że wymaga zgody); brak aplikacji na szynie → czytelny błąd narzędzia.
- Done when:
  - `make test` → kod 0
  - headless: `gdbus call --session -d pl.local.AiPanel -o /pl/local/AiPanel/Clipboard -m pl.local.AiPanel.Clipboard.WriteText "'abc'"` a potem `ReadText` → `('abc',)`
- Tests: integracja (GUI, Xvfb): zapis i odczyt przez D-Bus; MCP `tools/list` bez `--allow-write` nie zawiera `clipboard_write`, z flagą zawiera; `clipboard_read` przez MCP zwraca tekst; aplikacja niedziałająca → błąd narzędzia.

### UAT S11
- UAT-S11-1: Given serwer MCP When proszę o listę narzędzi Then widzę `notify` i `clipboard_read`, a `clipboard_write` tylko z `--allow-write`
  - Verify: polecenie `printf … | .venv/bin/python mcp/gnome_mcp.py` z S11-T1 → `notify`, `clipboard_read`, brak `clipboard_write`; z `--allow-write` → jest `clipboard_write`
- UAT-S11-2: Given serwer MCP podpięty do agenta (`mcp = ["gnome"]`) When agent startuje sesję Then dostaje serwer w `session/new`
  - Verify: `.venv/bin/pytest -q -k test_mcp_server_passed_to_agent` → passed (fałszywy agent `--record` zawiera `"command": "gnome-ai-panel-mcp"`)
- UAT-S11-3: Given prawdziwy agent z serwerem MCP When proszę „wyślij mi powiadomienie” Then panel pyta o zgodę i po zatwierdzeniu pojawia się powiadomienie GNOME `[manual]`
  - Verify: `make install`, agent Kiro z `mcp = ["gnome"]`; obserwacja
