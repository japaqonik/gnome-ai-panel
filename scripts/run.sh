#!/usr/bin/env bash
# make run: start the app in the background on the current desktop session (PLAN, Commands).
# PID in .run/app.pid, stdout/stderr in .run/app.log. Waits up to 10 s for "ui ready".
set -euo pipefail
# shellcheck source=scripts/run-common.sh
. "$(dirname "$0")/run-common.sh"

if pid=$(running "$APP_PID" "$APP_MATCH"); then
    if [[ -f $HEADLESS_ENV ]]; then
        say "run: a headless instance is running (pid $pid); run 'make stop' first"
        exit 1
    fi
    say "run: already running (pid $pid)"
    exit 0
fi
# Clean up leftovers of an earlier run (stale pid files, headless Xvfb/dbus).
"$ROOT/scripts/stop.sh" >/dev/null

[[ -x $PYTHON ]] || { say "run: $PYTHON missing, run 'make setup'"; exit 1; }
mkdir -p "$RUN"
: >"$APP_LOG"

cd "$ROOT"
setsid "$PYTHON" -m app --background </dev/null >>"$APP_LOG" 2>&1 &
pid=$!
echo "$pid" >"$APP_PID"

status=0
wait_ready "$pid" "$APP_LOG" || status=$?
if ((status == 0)); then
    say "run: ui ready (pid $pid, log $APP_LOG)"
    exit 0
fi
if ((status == 2)); then
    rc=0
    wait "$pid" || rc=$?
    rm -f "$APP_PID"
    if ((rc == 0)); then
        # GApplication handed over to an instance that was already running on this session.
        say "run: pl.local.AiPanel is already running on this session (not started by make run)"
        exit 0
    fi
    say "run: the app exited with code $rc; last log lines:"
else
    say "run: no 'ui ready' within ${READY_TIMEOUT} s; stopping; last log lines:"
    "$ROOT/scripts/stop.sh" >/dev/null || true
fi
tail -n 20 "$APP_LOG" >&2 || true
exit 1
