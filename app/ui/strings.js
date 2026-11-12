// All user-visible texts of the chat UI (NFR-8). Classic script: exposes window.aiPanelStrings.
'use strict';

window.aiPanelStrings = Object.freeze({
    copyCode: 'Kopiuj',
    copyCodeLabel: 'Kopiuj kod',
    copied: 'Skopiowano',
    copyFailed: 'Nie skopiowano',

    messagesLabel: 'Rozmowa',
    promptLabel: 'Wiadomość do agenta',
    promptPlaceholder: 'Napisz wiadomość… (Enter wysyła, Shift+Enter nowa linia)',
    send: 'Wyślij',
    sendLabel: 'Wyślij wiadomość',
    stop: 'Zatrzymaj',
    stopLabel: 'Zatrzymaj odpowiedź',
    noAgent: 'Brak agenta',
    // Header: agent and model selectors, mode badge (FR-12, FR-28).
    agentLabel: 'Agent',
    modelLabel: 'Model',
    badges: Object.freeze({
        tools: 'Agent z narzędziami',
        chat: 'Czysty czat',
    }),
    badgeTitles: Object.freeze({
        tools: 'Agent ACP: może używać narzędzi, np. czytać pliki i uruchamiać polecenia',
        chat: 'Tylko rozmowa z modelem, bez dostępu do narzędzi',
    }),
    errorTitle: 'Błąd',
    // Fallback label of the agent's stderr in an error card (Python normally sends it).
    stderrLabel: 'Ostatnie linie stderr agenta',
    // Button of the error card shown when the agent will not be restarted any more.
    newChat: 'Nowa rozmowa',
    // Markers for stop reasons other than end_turn (ACP StopReason).
    stopReasons: Object.freeze({
        cancelled: 'Przerwano',
        max_tokens: 'Przerwano: osiągnięto limit tokenów',
        max_turn_requests: 'Przerwano: osiągnięto limit kroków agenta',
        refusal: 'Agent odmówił odpowiedzi',
    }),
    // Thinking block header: while the agent is still thinking / afterwards.
    thinkingActive: 'Myśli…',
    thinkingDone: 'Myślenie',
    // Tool cards.
    toolUntitled: 'Narzędzie',
    toolInput: 'Wejście',
    toolOutput: 'Wynik',
    // Output item of type "terminal" (ACP): only its id is known to the panel.
    toolTerminal: 'Terminal',
    toolStatus: Object.freeze({
        pending: 'Oczekuje',
        in_progress: 'W toku',
        completed: 'Zakończone',
        failed: 'Niepowodzenie',
        cancelled: 'Anulowane',
    }),
    // ACP ToolKind of a tool call (permission dialog); unknown kinds are shown as sent.
    toolKinds: Object.freeze({
        read: 'Odczyt',
        edit: 'Edycja',
        delete: 'Usuwanie',
        move: 'Przenoszenie',
        search: 'Wyszukiwanie',
        execute: 'Wykonanie polecenia',
        think: 'Myślenie',
        fetch: 'Pobieranie',
        switch_mode: 'Zmiana trybu',
        other: 'Inne',
    }),
    // Permission dialog.
    permissionHeading: 'Agent prosi o zgodę',
    permissionKind: 'Rodzaj:',
    permissionInput: 'Wejście',
    permissionNoInput: '(brak danych wejściowych)',
    permissionQueued: 'Oczekujące prośby: ',
    // Labels of options the agent sent without a name, by ACP PermissionOptionKind.
    permissionOptions: Object.freeze({
        allow_once: 'Zezwól',
        allow_always: 'Zezwól zawsze',
        reject_once: 'Odrzuć',
        reject_always: 'Odrzuć zawsze',
    }),
    // Shown only when the agent offers no reject option; answers with option_id null.
    permissionReject: 'Odrzuć',
});
