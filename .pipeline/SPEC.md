# GNOME AI Panel

Boczny panel czatu z AI dla pulpitu GNOME, wysuwany skrótem klawiszowym (styl Raven Sidebar), ale zamiast widżetów zawiera pełnoprawny czat z formatowaniem markdown, jak w claude.ai. Aplikacja jest **generycznym klientem ACP** (Agent Client Protocol): Kiro CLI, Claude i inne agenty podpina użytkownik jako wpisy w konfiguracji, a panel nie zakłada żadnego z nich z góry. Dodatkowo istnieje prosty tryb „czysty czat" przez API Anthropic. Wygląd i zachowanie panelu (szerokość, strona, zwijanie, ikona) oraz agenty i klucze są w pełni konfigurowalne przez użytkownika.

## 1. Cele

- Szybka rozmowa z AI z pulpitu jednym skrótem (np. `Super+A`).
- Wygląd panelu natywnego: przyklejony do prawej krawędzi, cała wysokość, **bez paska tytułowego** i bez przycisków okna.
- Ładne renderowanie odpowiedzi: markdown, listy, tabele, bloki kodu z podświetlaniem, kopiowanie kodu.
- **Jednolita integracja agentów**: Kiro i Claude tym samym protokołem, konfigurowane w pliku, bez zmian w kodzie.
- Streaming odpowiedzi, karty wywołań narzędzi, okienka próśb o zgodę.
- Opcjonalna integracja z systemem przez wspólny serwer MCP (schowek, powiadomienia itp.).
- **Konfigurowalna szerokość** panelu (px lub % ekranu, z limitem min/max, opcjonalnie zmiana szerokości przeciąganiem krawędzi).
- **Konfigurowalna strona**: lewa lub prawa krawędź ekranu (oraz wybór monitora).
- **Ikona w pasku GNOME**, która pokazuje i chowa panel oraz otwiera menu (nowa rozmowa, wybór agenta, ustawienia, zakończ).
- **Automatyczne zwijanie** po kliknięciu poza panelem (z możliwością wyłączenia i z przyciskiem „przypnij", który trzyma panel otwarty).
- **Zero założeń**: żaden agent, komenda, klucz API, zmienna środowiskowa ani katalog nie są zaszyte w kodzie. Użytkownik wszystko ustawia sam, w oknie ustawień albo w pliku.

### Poza zakresem (na razie)

- Wiele monitorów z osobnymi panelami.
- Synchronizacja historii między urządzeniami.
- Rola pełnego IDE (edycja projektów, diffy), od tego są Kiro IDE i edytory.

## 2. Architektura

```
┌─────────────────────────────┐        ┌───────────────────────────────────┐
│ Rozszerzenie GNOME Shell    │        │ Aplikacja GTK4 (Python)           │
│ (GJS, ESM, GNOME 45+)       │        │                                   │
│  - skrót i ikona w pasku    │ okno   │  ┌─────────────────────────────┐  │
│  - szerokość i strona (L/P) │◄──────►│  │ WebKitGTK (UI czatu)        │  │
│  - always-on-top, ukrycie   │        │  │ marked + highlight.js       │  │
│    z Alt+Tab i przeglądu    │        │  │ + DOMPurify                 │  │
│  - animacja, zwijanie       │        │  └──────────────▲──────────────┘  │
└─────────────────────────────┘        │                 │ JS bridge       │
                                       │  ┌──────────────▼──────────────┐  │
                                       │  │ Warstwa backendów           │  │
                                       │  │  ├─ AcpBackend (generyczny) │  │
                                       │  │  └─ ApiBackend (opcjonalny) │  │
                                       │  └───────┬─────────────┬───────┘  │
                                       └──────────┼─────────────┼──────────┘
                                                  │ stdio       │ HTTPS
                                       ┌──────────▼───┐   ┌─────▼─────────┐
                                       │ Agenty ACP   │   │ API Anthropic │
                                       │ kiro-cli acp │   └───────────────┘
                                       │ claude-agent-│
                                       │ acp, inne    │
                                       └──────┬───────┘
                                              │ MCP (opcjonalnie)
                                       ┌──────▼───────────────┐
                                       │ Serwer MCP „GNOME"   │
                                       └──────────────────────┘
```

Dlaczego dwa elementy: rozszerzenia działają wewnątrz procesu `gnome-shell`, nie mają WebKita, a błąd w nich może wywalić sesję. Cały interfejs jest więc w osobnej aplikacji, a rozszerzenie robi tylko to, czego aplikacja na Waylandzie zrobić nie może: pozycjonuje okno. (`gtk4-layer-shell` nie działa na GNOME, bo Mutter nie obsługuje protokołu layer-shell.)

## 3. Komponenty

### 3.1 Aplikacja GTK4 (Python + PyGObject)

- Okno z `set_decorated(False)`, stały `application_id` / `WM_CLASS` (np. `pl.local.AiPanel`), po którym rozszerzenie znajdzie okno.
- Działa w tle (`Gio.Application` z `hold()`), więc panel otwiera się natychmiast.
- Zawartość: jeden `WebKit.WebView` z lokalną stroną HTML.
- Akcje `Gio.Action` wystawione przez D-Bus (`toggle`, `show`, `hide`, `new-chat`, `quit`), którymi steruje rozszerzenie (ikona w pasku, skrót) bez własnego protokołu.
- Okno ustawień (`Adw.PreferencesWindow`): lista agentów (dodaj, edytuj, usuń, przycisk „Test połączenia"), sekrety, serwery MCP, wygląd czatu. Konfiguracja jest też edytowalna ręcznie, a zmiany pliku są wczytywane bez restartu.
- Komunikacja Python ↔ strona: `UserContentManager` (JS → Python) i `evaluate_javascript` (Python → JS).
- Asynchroniczność: `asyncio` zintegrowany z pętlą GLib (np. `asyncio` + `gbulb`/`PyGObject` async) albo wątki robocze z `GLib.idle_add`.

### 3.2 Interfejs czatu (HTML/JS, lokalnie, bez CDN)

- `marked` (markdown), `highlight.js` (kod), `DOMPurify` (sanityzacja, bo odpowiedzi modelu są niezaufane).
- Pole wejściowe wieloliniowe (Enter wysyła, Shift+Enter nowa linia), przycisk stop.
- Przyrostowe renderowanie strumienia, kopiowanie bloków kodu.
- Zwijane bloki „myślenia" i karty wywołań narzędzi (status, wejście, wynik).
- Okienko zgody (Zezwól / Odrzuć) dla próśb agenta o uprawnienia.
- Wybór agenta i modelu w nagłówku, motyw jasny/ciemny z systemu.
- Linki otwierane w domyślnej przeglądarce, nie w panelu.

### 3.3 Rozszerzenie GNOME Shell

- `metadata.json` + `extension.js` (ESM, GNOME 45+), `prefs.js` (okno ustawień w `Adw`) i `schemas/` (GSettings).
- **Ikona w pasku GNOME**: `PanelMenu.Button` dodany przez `Main.panel.addToStatusArea`. GNOME nie ma klasycznego trayu, więc „tray" to górny pasek. Lewy klik pokazuje lub chowa panel, a menu zawiera: nową rozmowę, wybór agenta, ustawienia i zakończenie aplikacji. Ikonę można wyłączyć w ustawieniach.
- **Skrót klawiszowy** przez `Main.wm.addKeybinding`, konfigurowalny.
- **Pokazywanie i chowanie**: rozszerzenie wywołuje akcję `toggle` aplikacji (D-Bus), a gdy okno się pojawia, ustawia je w odpowiednim miejscu. Jeśli aplikacja nie działa, uruchamia ją (`Gio.AppInfo`).
- **Pozycja i rozmiar**: znalezienie okna po `wm_class`, przesunięcie do wybranej krawędzi (lewej lub prawej) i rozciągnięcie na wysokość obszaru roboczego (`move_resize_frame`), z uwzględnieniem górnego paska. Okno na wszystkich pulpitach, na wierzchu, pominięte w Alt+Tab i w przeglądzie.
- **Szerokość**: w pikselach lub procentach szerokości monitora, z limitem minimum i maksimum. Opcjonalnie uchwyt na wewnętrznej krawędzi, którym użytkownik zmienia szerokość przeciąganiem, a nowa wartość zapisuje się w ustawieniach.
- **Strona i monitor**: `left` / `right`, monitor główny, ten z kursorem albo wybrany z listy.
- **Zwijanie po kliknięciu poza panelem**: gdy panel jest widoczny, rozszerzenie nasłuchuje zdarzeń myszy na scenie (`global.stage`, `captured-event`) i chowa panel, jeśli kliknięcie wypadło poza jego prostokątem. Zdarzenie jest przepuszczane dalej, więc kliknięcie trafia też do okna pod spodem. Dodatkowe, osobno włączane wyzwalacze: utrata fokusu (`notify::focus-window`) i klawisz Esc.
- **Przypięcie**: przycisk w nagłówku panelu wyłącza automatyczne zwijanie do czasu odpięcia.
- **Animacja** wsuwania i chowania (`Clutter` easing), z możliwością wyłączenia i ustawienia czasu.
- **Ustawienia na żywo**: zmiana szerokości, strony, skrótu czy zwijania w oknie ustawień działa od razu (obserwacja `GSettings`), bez przeładowania rozszerzenia.

#### Ustawienia układu (GSettings)

| Klucz | Znaczenie | Przykład |
|---|---|---|
| `side` | strona ekranu | `left` / `right` |
| `width` | szerokość | `480` (px) lub `30%` |
| `min-width`, `max-width` | limity przy zmianie rozmiaru | `320`, `900` |
| `monitor` | który monitor | `primary` / `pointer` / `1` |
| `shortcut` | skrót pokazania/schowania | `<Super>a` |
| `show-tray-icon` | ikona w pasku | `true` |
| `collapse-on-click-outside` | zwijanie po kliknięciu poza panelem | `true` |
| `collapse-on-focus-loss` | zwijanie po utracie fokusu | `false` |
| `collapse-on-escape` | zwijanie klawiszem Esc | `true` |
| `animation-ms` | czas animacji (0 = wyłączona) | `180` |

Wszystkie wartości można zmienić w oknie ustawień rozszerzenia albo przez `dconf` / `gsettings`.

## 4. Warstwa backendów

Wspólny interfejs, żeby UI nie wiedziało, kto odpowiada:

```python
class Backend(Protocol):
    name: str
    def new_session(self) -> str: ...
    def send(self, session_id: str, prompt: str) -> AsyncIterator[Event]: ...
    def respond_permission(self, request_id: str, allow: bool) -> None: ...
    def cancel(self, session_id: str) -> None: ...

# Event: TextDelta | ThinkingDelta | ToolCall | ToolUpdate
#      | PermissionRequest | Done | Error
```

### 4.1 AcpBackend (generyczny klient ACP)

Jeden kod obsługuje każdego agenta zgodnego z ACP. Różnice między agentami są wyłącznie w konfiguracji.

- Proces podrzędny uruchamiany z konfiguracji (komenda, argumenty, zmienne środowiskowe, katalog roboczy). Komunikacja: JSON-RPC 2.0 po stdio, linia po linii.
- Przepływ: `initialize` (negocjacja możliwości) → utworzenie sesji (katalog roboczy, lista serwerów MCP) → wysłanie promptu → powiadomienia o aktualizacji sesji (fragmenty tekstu i myślenia, wywołania narzędzi i ich statusy) → koniec tury.
- Prośby o uprawnienia przychodzą od agenta jako żądanie do klienta, a panel pokazuje okienko i odsyła decyzję.
- Anulowanie tury przyciskiem stop.
- Jeden proces na agenta, osobna sesja na rozmowę, restart procesu po awarii.
- Panel nie ma wbudowanej listy agentów ani zakładanych komend: wszystko, co poniżej, to **przykłady** do wypełnienia przez użytkownika.
- Dokładne nazwy metod i typów zdarzeń: weryfikować w specyfikacji ACP (agentclientprotocol.com) i w dokumentacji Kiro (CLI → ACP). Można użyć oficjalnego SDK, jeśli istnieje wersja dla Pythona, albo napisać cienką własną warstwę (protokół jest prosty).

#### Przykład: Kiro (szablon, nie ustawienie domyślne)

- Komenda: `kiro-cli acp`.
- Uwierzytelnianie: istniejące logowanie `kiro-cli` albo, bez okna przeglądarki, zmienna `KIRO_API_KEY` (klucz z ustawień konta; to tryb headless CLI, nie osobne API HTTP). Obie drogi są opcjonalne i zależą od użytkownika, panel niczego nie zakłada. Dostępność kluczy w danym planie do sprawdzenia.
- Kiro nie ma (z tego, co wiadomo) endpointu HTTP do rozmowy z modelem, więc ACP przez stdio jest właściwym interfejsem.

#### Przykład: Claude (szablon, nie ustawienie domyślne)

- Komenda: `claude-agent-acp`, adapter ACP oparty na Claude Agent SDK (utrzymywany w organizacji agentclientprotocol, instalacja przez npm, wymaga Node.js).
- Uwierzytelnianie: zmienne środowiskowe przekazane procesowi, np. `ANTHROPIC_API_KEY`, o ile użytkownik ją ustawi (źródło wartości wybiera użytkownik, patrz sekcja 5).
- To Claude Code jako agent z narzędziami, nie goły czat, więc wymaga okrojenia (patrz sekcja 6).

#### Kolejne agenty

Każdy agent zgodny z ACP (np. Gemini CLI, Codex) dopisuje się jako kolejny wpis w konfiguracji, bez zmian w kodzie.

### 4.2 ApiBackend (opcjonalny, czysty czat)

Do szybkich pytań bez narzędzi i bez ryzyka dostępu do plików.

- `POST https://api.anthropic.com/v1/messages` z `"stream": true`, nagłówki `x-api-key`, `anthropic-version`, `content-type`.
- Parsowanie strumienia SSE i mapowanie na `TextDelta`.
- Historię trzyma aplikacja i wysyła ją w każdym żądaniu.
- Modele do wyboru w konfiguracji, np. `claude-sonnet-5-5` (domyślny) i `claude-haiku-5-5` (szybszy, tańszy). Konfigurowalny prompt systemowy.
- Rozliczenie za tokeny, niezależnie od abonamentów konsumenckich.

### 4.3 Porównanie

| | ACP: Kiro | ACP: Claude | API: Claude |
|---|---|---|---|
| Rola | agent z narzędziami | agent z narzędziami | zwykły czat |
| Uruchomienie | `kiro-cli acp` | `claude-agent-acp` | HTTPS |
| Uwierzytelnienie | logowanie CLI lub `KIRO_API_KEY` | `ANTHROPIC_API_KEY` | `ANTHROPIC_API_KEY` |
| Koszt | limity abonamentu Kiro | tokeny API | tokeny API |
| Dostęp do plików i powłoki | tak, wymaga ograniczeń | tak, wymaga ograniczeń | brak |
| Złożoność | średnia (jeden wspólny klient ACP) | średnia (ten sam klient) | niska |

## 5. Konfiguracja

### 5.1 Zasady

- **Nic nie jest zaszyte.** Panel nie zakłada, że istnieje `kiro-cli`, `claude-agent-acp` ani żaden inny program, i nie wymaga żadnego konkretnego klucza. Po pierwszym uruchomieniu lista agentów jest pusta, a panel pokazuje ekran startowy „Dodaj agenta".
- **Szablony zamiast domyślnych.** W kreatorze dodawania agenta można wybrać gotowy szablon (Kiro ACP, Claude ACP, Claude API, własny), ale szablon tylko wypełnia pola formularza. Każde pole (komenda, argumenty, katalog roboczy, zmienne środowiskowe, serwery MCP, limity czasu) można zmienić.
- **Dowolne zmienne środowiskowe.** Użytkownik sam decyduje, jakie zmienne dostaje dany agent i skąd pochodzą ich wartości. Brak klucza nie jest błędem, jeśli agent go nie potrzebuje (np. korzysta z własnego logowania).
- **Dwie warstwy**, każda z własnym oknem ustawień i możliwością edycji ręcznej.
- **Walidacja i test.** Przycisk „Test połączenia" uruchamia agenta, wykonuje `initialize` i pokazuje wynik albo czytelny błąd (brak komendy, zły klucz, nieobsługiwany protokół).

### 5.2 Warstwa 1: układ i zachowanie panelu (GSettings)

Definiuje ją rozszerzenie GNOME (tabela w sekcji 3.3): strona, szerokość, monitor, skrót, ikona w pasku, zwijanie, animacja. Edycja w oknie ustawień rozszerzenia lub przez `dconf` / `gsettings`, zmiany stosowane na żywo.

### 5.3 Warstwa 2: agenty, sekrety, MCP, wygląd czatu (plik TOML)

Plik `~/.config/gnome-ai-panel/config.toml`, edytowalny w oknie ustawień aplikacji lub ręcznie (zmiany wczytywane bez restartu). Wartości poniżej są wyłącznie ilustracją formatu, a nie ustawieniami domyślnymi:

```toml
default_agent = "moj-agent"          # opcjonalne; może być puste

[agents.moj-agent]
type = "acp"
command = "/ścieżka/do/agenta"       # dowolna komenda
args = ["acp"]                       # dowolne argumenty
cwd = "~/.cache/ai-panel"
startup_timeout_s = 20
mcp = []                             # nazwy serwerów MCP z sekcji [mcp.*]

[agents.moj-agent.env]               # dowolne zmienne, wszystkie opcjonalne
SOME_API_KEY = { source = "keyring", name = "moj-agent-key" }
SOME_OTHER   = { source = "env",     name = "ZMIENNA_Z_SYSTEMU" }
FROM_TOOL    = { source = "command", cmd = "pass show ai/klucz" }
ASK_ME       = { source = "prompt" }               # pytaj przy uruchomieniu
PLAIN_VALUE  = { source = "literal", value = "tekst" }  # nie dla sekretów

[agents.szybki-czat]
type = "api"                         # prosty czat przez HTTP, bez narzędzi
endpoint = "https://adres/api"       # dowolny endpoint zgodny z formatem
model = "nazwa-modelu"
system_prompt = "Odpowiadaj zwięźle i po polsku."
api_key = { source = "keyring", name = "szybki-czat-key" }

[mcp.gnome]                          # opcjonalny serwer MCP
command = "gnome-ai-panel-mcp"
args = []

[chat]
font_size = 14
theme = "system"                     # system / light / dark
history_dir = "~/.local/share/gnome-ai-panel"
```

Źródła wartości (`source`):

| `source` | Skąd pochodzi wartość | Uwagi |
|---|---|---|
| `keyring` | Secret Service (libsecret) | zalecane dla kluczy, wartość nigdy nie trafia do pliku |
| `env` | zmienna środowiskowa sesji | przydatne, gdy użytkownik zarządza kluczami sam |
| `command` | wynik polecenia (np. `pass`, `op`) | polecenie uruchamiane przy starcie agenta |
| `prompt` | pytanie w UI | wartość tylko w pamięci, nie jest zapisywana |
| `literal` | tekst w pliku | do wartości niesekretnych |

Historia rozmów: JSON, jeden plik na rozmowę, w katalogu z `history_dir`.

## 6. Bezpieczeństwo

Agenty ACP (Kiro, Claude Code) potrafią uruchamiać polecenia i modyfikować pliki, więc w panelu trzeba je ograniczyć:

- Osobna, okrojona konfiguracja agenta do rozmowy: dla Kiro własny agent w `.kiro/agents/` bez narzędzi zapisu i powłoki, dla Claude wyłączone wbudowane narzędzia albo lista dozwolonych narzędzi przekazana przy tworzeniu sesji.
- Sesje uruchamiane w pustym katalogu roboczym (`~/.cache/ai-panel/`), nie w katalogu domowym.
- Każda prośba o uprawnienia widoczna dla użytkownika; brak automatycznego zatwierdzania.
- Wyraźne oznaczenie w UI, że aktywny jest tryb agenta z narzędziami.
- Sanityzacja wszystkiego, co wraca z modelu, przed wstawieniem do DOM.
- Sekrety najlepiej w libsecret (`source = "keyring"`), nigdy w repozytorium ani w logach; wartości `literal` ostrzegane w oknie ustawień jako niezalecane dla kluczy.
- Polecenia z `command` i komendy agentów uruchamiane z uprawnieniami użytkownika, więc panel nie importuje konfiguracji z niezaufanych źródeł bez potwierdzenia.
- Serwer MCP „GNOME": najpierw narzędzia tylko do odczytu lub niegroźne (powiadomienie, schowek), a każde narzędzie z efektem ubocznym wymaga zgody.

## 7. Struktura repozytorium

```
gnome-ai-panel/
├── app/
│   ├── main.py              # Gio.Application, okno, bridge do WebView
│   ├── config.py            # config.toml, źródła sekretów (keyring/env/komenda/prompt)
│   ├── settings_ui.py       # okno ustawień (Adw.PreferencesWindow)
│   ├── backends/
│   │   ├── base.py          # interfejs Backend i typy zdarzeń
│   │   ├── acp.py           # generyczny klient ACP
│   │   └── api.py           # czysty czat przez API
│   ├── storage.py           # historia rozmów
│   └── ui/                  # index.html, app.js, style.css, vendor/
├── mcp/
│   └── gnome_mcp.py         # opcjonalny serwer MCP z narzędziami systemowymi
├── extension/
│   ├── metadata.json
│   ├── extension.js         # panel, ikona w pasku, skrót, zwijanie, pozycja
│   ├── prefs.js             # okno ustawień układu
│   ├── schemas/             # GSettings (strona, szerokość, zwijanie, ...)
│   └── stylesheet.css
├── data/                    # plik .desktop, ikona
└── README.md
```

## 8. Plan prac

1. **Prototyp klienta ACP w terminalu**: uruchomienie dowolnego agenta ACP z konfiguracji, `initialize`, sesja, prompt i wypisanie strumienia zdarzeń. Test z `kiro-cli acp`, potem ten sam kod z `claude-agent-acp`. Weryfikuje, że jedna warstwa obsługuje oba agenty.
2. **Konfiguracja**: wczytywanie `config.toml`, źródła sekretów (keyring, env, komenda, prompt), walidacja, wczytywanie zmian bez restartu.
3. **Okno czatu**: GTK4 + WebKit bez dekoracji, markdown i podświetlanie, wysyłanie i streaming. Najpierw jeden agent.
4. **Pełna obsługa ACP w UI**: karty narzędzi, bloki myślenia, okienko zgód, anulowanie, przełącznik agentów, ekran „Dodaj agenta" z szablonami i „Test połączenia".
5. **Rozszerzenie GNOME, część podstawowa**: akcje D-Bus aplikacji, skrót, pozycjonowanie z wyborem strony (lewo/prawo) i szerokości, ukrycie z Alt+Tab.
6. **Rozszerzenie GNOME, część interaktywna**: ikona w pasku z menu, zwijanie po kliknięciu poza panelem (plus utrata fokusu i Esc), przypinanie, animacja, zmiana szerokości przeciąganiem, okno ustawień i schemat GSettings z ustawieniami na żywo.
7. **ApiBackend**: tryb szybkiego czatu bez narzędzi.
8. **Okno ustawień aplikacji**: edycja agentów, sekretów i MCP z poziomu UI.
9. **Dopieszczenie**: historia, wiele rozmów, wklejanie obrazków, motyw, autostart, pakowanie.
10. **(Później) Serwer MCP „GNOME"**: wspólne narzędzia systemowe dla agentów.

## 9. Ryzyka i uwagi

- **API rozszerzeń zmienia się między wersjami GNOME**: potrzebne testy po aktualizacjach.
- **Wayland**: pozycjonowanie okien tylko z poziomu rozszerzenia.
- **Ikona w „trayu"**: GNOME nie ma klasycznego trayu, więc ikona jest przyciskiem w górnym pasku dodanym przez rozszerzenie. Wyświetlanie w innych środowiskach (protokół StatusNotifierItem) wymagałoby osobnej obsługi.
- **Zwijanie po kliknięciu poza panelem**: działanie zdarzeń myszy na scenie powłoki trzeba sprawdzić na docelowej wersji GNOME, a utrata fokusu jest rezerwowym wyzwalaczem. Trzeba uważać, żeby kliknięcie w ikonę w pasku nie zwijało i od razu nie rozwijało panelu na nowo.
- **Specyfika agentów**: ACP ujednolica protokół, ale agenty różnią się możliwościami, nazwami modeli i sposobem konfiguracji narzędzi, więc UI powinno degradować się łagodnie, gdy agent czegoś nie wspiera.
- **Zależności**: adapter Claude wymaga Node.js; trzeba obsłużyć brak komendy z czytelnym komunikatem.
- **WebKitGTK w Flatpaku**: sandbox utrudnia uruchamianie `kiro-cli` i adaptera, więc na start pakowanie natywne (skrypt instalacyjny).
- **Koszty**: tryby API i Claude ACP rozliczają tokeny, a Kiro zużywa limit abonamentu; warto pokazywać zużycie.
- **Zmiany w ACP**: protokół jest młody, więc przypiąć wersje i śledzić zmiany.

## 10. Otwarte pytania

- Wersja GNOME i czy docelowo tylko Wayland.
- Czy zapamiętywać rozmowy między uruchomieniami, czy każda sesja od zera.
- Czy dla Claude wystarczy tryb API (czysty czat), czy adapter ACP jest potrzebny od początku.
- Czy panel ma pokazywać się na każdym monitorze osobno, czy tylko na jednym (domyślnie jeden, wybierany w ustawieniach).
