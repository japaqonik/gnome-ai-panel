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
    errorTitle: 'Błąd',
    // Markers for stop reasons other than end_turn (ACP StopReason).
    stopReasons: Object.freeze({
        cancelled: 'Przerwano',
        max_tokens: 'Przerwano: osiągnięto limit tokenów',
        max_turn_requests: 'Przerwano: osiągnięto limit kroków agenta',
        refusal: 'Agent odmówił odpowiedzi',
    }),
});
