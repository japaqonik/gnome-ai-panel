# Shared helpers for scripts/run.sh, scripts/run-headless.sh and scripts/stop.sh.
# Sourced, not executed. Sets ROOT (repository root) and RUN (state directory, default .run;
# AI_PANEL_RUN_DIR overrides it so tests do not touch a developer's running instance).

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
RUN=${AI_PANEL_RUN_DIR:-$ROOT/.run}
PYTHON=$ROOT/.venv/bin/python

APP_PID=$RUN/app.pid
APP_LOG=$RUN/app.log
XVFB_PID=$RUN/xvfb.pid
DBUS_PID=$RUN/dbus.pid
HEADLESS_ENV=$RUN/headless.env
RUNTIME_DIR_FILE=$RUN/runtime-dir
HEADLESS_HOME=$RUN/home

# Seconds to wait for "ui ready" in the log (PLAN: 10 s).
READY_TIMEOUT=${READY_TIMEOUT:-10}

say() { printf '%s\n' "$*" >&2; }

# pid_from_file <pidfile> -> prints the pid if the file holds a number.
pid_from_file() {
    local pid
    [[ -f $1 ]] || return 1
    read -r pid <"$1" || true
    [[ $pid =~ ^[0-9]+$ ]] || return 1
    printf '%s\n' "$pid"
}

# pid_matches <pid> <substring of its command line>: alive and really the process we started
# (protects against a reused pid).
pid_matches() {
    local pid=$1 want=$2 cmdline
    kill -0 "$pid" 2>/dev/null || return 1
    cmdline=$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null) || return 1
    [[ $cmdline == *"$want"* ]]
}

# running <pidfile> <substring>: prints the pid when the recorded process is alive.
running() {
    local pid
    pid=$(pid_from_file "$1") || return 1
    pid_matches "$pid" "$2" || return 1
    printf '%s\n' "$pid"
}

APP_MATCH="-m app"
XVFB_MATCH="Xvfb"
DBUS_MATCH="dbus-daemon"

# wait_ready <pid> <log>: waits until the log has "ui ready" or the process dies.
wait_ready() {
    local pid=$1 log=$2 deadline=$((SECONDS + READY_TIMEOUT))
    while ((SECONDS < deadline)); do
        if grep -q "ui ready" "$log" 2>/dev/null; then
            return 0
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            return 2
        fi
        sleep 0.1
    done
    grep -q "ui ready" "$log" 2>/dev/null
}
