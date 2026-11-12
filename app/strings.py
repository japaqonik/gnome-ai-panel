"""User-facing texts of the Python side (Polish, NFR-8), kept in one place.

Templates use ``str.format`` placeholders.
"""

# -- config.toml validation (app/config.py) ------------------------------------------------
CFG_READ_ERROR = "nie można odczytać pliku: {reason}"
CFG_NOT_UTF8 = "plik nie jest poprawnym tekstem UTF-8 (bajt {position})"
CFG_SYNTAX = "błąd składni TOML: {reason}"
CFG_PERMISSIONS = (
    "plik {file} jest zapisywalny przez grupę lub innych użytkowników (uprawnienia {mode}); "
    "zalecane: chmod 600"
)
CFG_REQUIRED = "wymagane"
CFG_EMPTY = "nie może być puste"
CFG_WRONG_TYPE = "oczekiwano: {expected}, jest: {actual}"
CFG_UNKNOWN_KEY = "nieznany klucz, pominięty"
CFG_UNKNOWN_AGENT_TYPE = "nieznany typ agenta „{value}” (dozwolone: {allowed})"
CFG_UNKNOWN_SOURCE = "nieznane źródło „{value}” (dozwolone: {allowed})"
CFG_INVALID_ID = "nieprawidłowy identyfikator „{value}”"
CFG_INVALID_ENV_NAME = "nieprawidłowa nazwa zmiennej środowiskowej „{value}”"
CFG_UNKNOWN_MCP = "nieznany serwer MCP „{value}” (brak sekcji [mcp.{value}])"
CFG_INVALID_MCP = "serwer MCP „{value}” ma błędy konfiguracji"
CFG_UNKNOWN_DEFAULT = "nieznany agent „{value}”"
CFG_INVALID_DEFAULT = "agent „{value}” ma błędy konfiguracji i został pominięty"
CFG_OUT_OF_RANGE = "wartość {value} poza zakresem {low}–{high}"
CFG_NOT_POSITIVE = "wartość musi być większa od zera"
CFG_CHOICE = "nieprawidłowa wartość „{value}” (dozwolone: {allowed})"
CFG_BAD_URL = "oczekiwano adresu http:// lub https://"
CFG_BAD_COMMAND_LINE = "nie można podzielić polecenia na argumenty: {reason}"
CFG_UNSUPPORTED_VALUE = "nieobsługiwany typ wartości: {actual}"
CFG_LITERAL_WARNING = (
    "źródło „literal” zapisuje wartość jawnie w pliku; dla kluczy użyj „keyring”, „env”, "
    "„command” lub „prompt”"
)

TYPE_NAMES = {
    "str": "tekst",
    "int": "liczba całkowita",
    "float": "liczba",
    "number": "liczba",
    "bool": "wartość logiczna",
    "list": "lista",
    "dict": "tabela",
    "date": "data",
    "datetime": "data i czas",
    "time": "czas",
    "NoneType": "brak wartości",
}

# -- value sources and secrets (app/secrets.py) --------------------------------------------
SECRET_NO_SERVICE = (
    "brak usługi Secret Service (keyring): {reason}; uruchom gnome-keyring albo użyj źródła "
    "„env” lub „command”"
)
SECRET_NO_BUS = "brak połączenia z szyną sesji D-Bus"
SECRET_NOT_RUNNING = "usługa org.freedesktop.secrets nie działa"
SECRET_SERVICE_ERROR = "błąd usługi Secret Service: {reason}"
SECRET_ITEM_LABEL = "GNOME AI Panel: {name}"
SECRET_CMD_EMPTY = "puste polecenie"
SECRET_CMD_START = "nie można uruchomić polecenia „{program}”: {reason}"
SECRET_CMD_FAILED = "polecenie „{program}” zakończyło się kodem {code}"
SECRET_CMD_TIMEOUT = "polecenie „{program}” nie zakończyło się w ciągu {timeout:g} s"
SECRET_CMD_NOT_UTF8 = "wynik polecenia „{program}” nie jest tekstem UTF-8"
SECRET_CMD_TOO_LONG = "wynik polecenia „{program}” jest dłuższy niż {limit} bajtów"
SECRET_NEEDS_INTERACTION = "„{label}”: wartość wymaga interakcji (brak terminala)"
SECRET_PROMPT_LABEL = "Wartość zmiennej {name}"
SECRET_VAR_ERROR = "zmienna {name}: {reason}"

# -- CLI (app/cli.py) ----------------------------------------------------------------------
CLI_DESCRIPTION = "Narzędzia wiersza poleceń GNOME AI Panel"
CLI_HELP_CHECK_CONFIG = "sprawdza plik konfiguracji i wypisuje błędy"
CLI_HELP_CONFIG_PATH = "ścieżka do pliku (domyślnie $AI_PANEL_CONFIG lub ~/.config/…)"
CLI_HELP_AGENTS = "wypisuje poprawnie skonfigurowanych agentów"
CLI_HELP_JSON = "wynik w formacie JSON"
CLI_WARNING_PREFIX = "ostrzeżenie: "
CLI_CONFIG_MISSING = "Brak pliku {file}: pusta konfiguracja (brak agentów)."
CLI_CONFIG_OK = "Konfiguracja poprawna: {file} (agenci: {agents}, serwery MCP: {mcp})."
CLI_CONFIG_ERRORS = "Błędy konfiguracji: {count} w {file}."
CLI_NO_AGENTS = "Brak skonfigurowanych agentów."
CLI_AGENTS_SKIPPED = "Pominięto błędnych agentów: {ids} (szczegóły: check-config)."
CLI_DEFAULT_MARK = " (domyślny)"
CLI_ERROR_PREFIX = "błąd: "
CLI_HELP_SECRET = "sekrety w keyringu (Secret Service)"
CLI_HELP_SECRET_SET = "zapisuje sekret; wartość ze standardowego wejścia"
CLI_HELP_SECRET_DELETE = "usuwa sekret"
CLI_HELP_SECRET_HAS = "sprawdza, czy sekret istnieje (kod 0: tak, 1: nie)"
CLI_HELP_SECRET_NAME = 'nazwa sekretu (jak w {source = "keyring", name = "…"})'
CLI_SECRET_PROMPT = "Wartość sekretu „{name}”: "
CLI_SECRET_SAVED = "Zapisano sekret „{name}”."
CLI_SECRET_DELETED = "Usunięto sekret „{name}”."
CLI_SECRET_EXISTS = "Sekret „{name}” istnieje."
CLI_SECRET_NOT_FOUND = "Brak sekretu „{name}”."
CLI_SECRET_EMPTY = "pusta wartość: podaj sekret na standardowym wejściu"
CLI_SECRET_TOO_LONG = "wartość dłuższa niż {limit} bajtów"
CLI_SECRET_BAD_NAME = "nieprawidłowa nazwa sekretu „{name}”"
CLI_SECRET_NOT_UTF8 = "wartość nie jest tekstem UTF-8"
CLI_HELP_CHAT = "jedna tura rozmowy z agentem; strumień zdarzeń na standardowe wyjście"
CLI_HELP_AGENT_ID = "identyfikator agenta z config.toml (lista: agents)"
CLI_HELP_PROMPT = "treść wiadomości"
CLI_HELP_CHAT_JSON = "zdarzenia jako JSON Lines (jeden obiekt JSON w linii)"
CLI_HELP_PERMISSION = (
    "odpowiedź na prośby agenta o zgodę: deny (domyślnie, odrzuca) albo allow (zezwala raz)"
)
CLI_HELP_CANCEL_AFTER = "anuluje turę po S sekundach (session/cancel)"
CLI_HELP_TEST_AGENT = "test połączenia: uruchamia agenta, initialize, session/new i zamyka go"
CLI_BAD_SECONDS = "oczekiwano nieujemnej liczby sekund, jest: {value}"
CLI_UNKNOWN_AGENT = "nieznany agent „{id}”."
CLI_AVAILABLE_AGENTS = "Dostępni agenci: {ids}."
CLI_SKIPPED_AGENT = (
    "agent „{id}” ma błędy konfiguracji i został pominięty (szczegóły: check-config)."
)
CLI_UNSUPPORTED_AGENT_TYPE = "agenci typu „{type}” nie są jeszcze obsługiwani w tej wersji."
CLI_INTERRUPTED = "przerwano."
CLI_HELP_UI_DUMP = "zrzut stanu okna (akcja debug-dump; aplikacja uruchomiona z AI_PANEL_DEBUG=1)"
CLI_UI_DUMP_NO_APP = (
    "nie można wywołać akcji debug-dump: {reason} (czy aplikacja działa z AI_PANEL_DEBUG=1, "
    "np. make run-headless, i czy wczytano .run/headless.env?)"
)
CLI_UI_DUMP_TIMEOUT = "aplikacja nie zapisała zrzutu {file} w ciągu {seconds:g} s"
CLI_PERMISSION_DENIED = "{title} → odrzucono (domyślnie; --permission allow zezwala)"
CLI_PERMISSION_DENIED_NO_ALLOW = "{title} → odrzucono (agent nie podał opcji zezwolenia)"
CLI_PERMISSION_ALLOWED = "{title} → zezwolono ({option})"
CLI_PERMISSION_OPTIONS = "{title}: prośba o zgodę, opcje: {options}"
CLI_TOOL_UNTITLED = "narzędzie {id}"
CLI_USAGE = "użyto {used} z {size} tokenów"
CLI_USAGE_COST = ", koszt {amount:g} {currency}"
CLI_TEST_AGENT = "Agent: {name}"
CLI_TEST_PROTOCOL = "protokół: {version}"
CLI_TEST_AUTH_METHODS = "metody logowania: {methods}"
CLI_TEST_NONE = "brak"
CLI_TEST_OK = "OK: agent odpowiada i utworzył sesję."
CLI_TEST_FAILED = "Test połączenia nie powiódł się: {message}"

# -- connection test (app/diagnostics.py) --------------------------------------------------
DIAG_UNKNOWN_AGENT_INFO = "(agent nie podał nazwy ani wersji)"
DIAG_UNSUPPORTED_TYPE = "Test połączenia dla agentów typu „{type}” nie jest jeszcze dostępny."
DIAG_UNEXPECTED = "Nieoczekiwany błąd podczas testu: {reason}"
DIAG_HINTS = {
    "spawn": "Sprawdź pola „command”, „args”, „cwd” i „env” agenta w pliku konfiguracji.",
    "timeout": (
        "Sprawdź, czy polecenie uruchamia agenta w trybie ACP (np. argument „acp”), albo "
        "zwiększ startup_timeout_s."
    ),
    "protocol": (
        "Agent nie rozmawia zgodnie z ACP w wersji obsługiwanej przez panel "
        "(protokół 1). Zaktualizuj agenta albo sprawdź jego argumenty."
    ),
    "crashed": "Agent zakończył działanie; jego komunikaty ze stderr są powyżej.",
}

# -- ACP backend (app/backends/acp.py) -----------------------------------------------------
ACP_COMMAND_NOT_FOUND = "Nie znaleziono polecenia: {command}"
ACP_SPAWN_FAILED = "Nie można uruchomić polecenia {command}: {reason}"
ACP_CWD_FAILED = "Nie można utworzyć katalogu roboczego {path}: {reason}"
ACP_ENV_FAILED = "Nie można przygotować środowiska agenta: {reason}"
ACP_MCP_ENV_FAILED = "Nie można przygotować serwera MCP „{id}”: {reason}"
ACP_STARTUP_TIMEOUT = "Agent nie odpowiedział w ciągu {timeout:g} s (startup_timeout_s)"
ACP_SESSION_TIMEOUT = "Agent nie utworzył sesji w ciągu {timeout:g} s"
ACP_REQUEST_TIMEOUT = "Agent nie odpowiedział na {method} w ciągu {timeout:g} s"
ACP_BAD_VERSION = "Nieobsługiwana wersja protokołu ACP: {version} (obsługiwana: {supported})"
ACP_BAD_RESPONSE = "Niepoprawna odpowiedź agenta na {method}"
ACP_REQUEST_FAILED = "Agent zwrócił błąd dla {method}: {reason}"
ACP_AUTH_REQUIRED = (
    "Agent wymaga zalogowania. Dostępne metody: {methods}. Zaloguj się w terminalu (np. "
    "poleceniem logowania swojego agenta) i spróbuj ponownie."
)
ACP_AUTH_NO_METHODS = "agent nie podał żadnej"
ACP_EXITED = "Proces agenta zakończył działanie (kod {code})."
ACP_EXITED_SIGNAL = "Proces agenta został zakończony sygnałem {signal}."
ACP_EXITED_UNKNOWN = "Proces agenta przestał odpowiadać (zamknął standardowe wyjście)."
ACP_EXITED_AT_START = "Agent zakończył działanie podczas uruchamiania."
ACP_STDERR_TAIL = "Ostatnie linie stderr:\n{stderr}"
ACP_RESTART_LIMIT = (
    "Agent ulegał awarii zbyt często ({count} ponowne uruchomienia w ciągu {window:g} s). "
    "Spróbuj ponownie za chwilę."
)
ACP_SESSION_LOST = "Sesja agenta została utracona, bo jego proces zakończył działanie."
ACP_UNKNOWN_SESSION = "Nieznana sesja: {session_id}"
ACP_TURN_RUNNING = "W tej sesji trwa już tura"
ACP_CLOSED = "Połączenie z agentem zostało zamknięte"

# -- chat controller (app/controller.py) and bridge (app/bridge.py) -----------------------
CTRL_TURN_RUNNING = "Poprzednia odpowiedź jeszcze trwa. Poczekaj na nią albo ją przerwij."
CTRL_NO_AGENT = "Brak skonfigurowanego agenta. Dodaj agenta w pliku konfiguracji."
CTRL_AGENT_UNSUPPORTED = "Agent „{name}” typu „{type}” nie jest jeszcze obsługiwany."
CTRL_EMPTY_PROMPT = "Wiadomość jest pusta."
CTRL_INVALID_MESSAGE = "Nieprawidłowa wiadomość z interfejsu."
CTRL_UNEXPECTED = "Nieoczekiwany błąd. Szczegóły są w dzienniku aplikacji."
CTRL_TURN_ENDED = "Tura zakończyła się bez odpowiedzi agenta."
CTRL_AGENT_RESTARTED = "Agent został uruchomiony ponownie, poprzedni kontekst utracony"
CTRL_SESSION_ABANDONED = (
    "Agent nie potwierdził przerwania poprzedniej odpowiedzi, więc rozpoczęto nową sesję; "
    "poprzedni kontekst utracony"
)
CTRL_OPTION_FAILED = "Nie udało się zmienić ustawienia „{name}”: {reason}"
CTRL_BLOCKED = (
    "Agent ulegał awarii zbyt często i w tej rozmowie nie zostanie uruchomiony ponownie. "
    "Rozpocznij nową rozmowę."
)

# Error messages in the chat (S4-T3): title and hint by ``Error.kind``.
CHAT_ERROR_TITLES = {
    "spawn": "Nie można uruchomić agenta",
    "timeout": "Agent nie odpowiada",
    "protocol": "Niezgodny protokół agenta",
    "auth": "Agent wymaga zalogowania",
    "http": "Błąd połączenia",
    "crashed": "Agent przestał działać",
    "other": "Błąd",
}
CHAT_ERROR_HINTS = {
    "spawn": "Sprawdź pola „command”, „args”, „cwd” i „env” agenta w pliku konfiguracji.",
    "timeout": (
        "Sprawdź, czy polecenie uruchamia agenta w trybie ACP (np. argument „acp”), albo "
        "zwiększ startup_timeout_s w konfiguracji agenta."
    ),
    "protocol": (
        "Agent nie rozmawia zgodnie z ACP w wersji obsługiwanej przez panel (protokół 1). "
        "Zaktualizuj agenta albo sprawdź jego argumenty."
    ),
    "auth": (
        "Zaloguj się w terminalu, np. poleceniem logowania swojego agenta, i wyślij "
        "wiadomość ponownie."
    ),
    "crashed": (
        "Następna wiadomość uruchomi agenta ponownie; poprzedni kontekst rozmowy zostanie utracony."
    ),
}
CHAT_AUTH_MESSAGE = "Agent nie utworzy sesji, dopóki się nie zalogujesz."
CHAT_AUTH_METHODS = "Dostępne metody logowania:"
CHAT_AUTH_NO_METHODS = "Agent nie podał metod logowania."
CHAT_RESTART_LIMIT_HINT = "Rozpocznij nową rozmowę, aby spróbować ponownie."
CHAT_STDERR_LABEL = "Ostatnie linie stderr agenta"
