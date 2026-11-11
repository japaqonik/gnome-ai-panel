#!/usr/bin/env bash
# make run-headless: the app on a private Xvfb display and a private D-Bus session bus, with
# HOME/XDG_* isolated in .run/home and a fresh XDG_RUNTIME_DIR (mode 0700), so nothing reaches
# the user's session, keyring or /run/user/<uid>. AI_PANEL_DEBUG=1.
# Writes the variables to .run/headless.env. Usage afterwards:
#   source .run/headless.env && gapplication action pl.local.AiPanel toggle
set -euo pipefail
# shellcheck source=scripts/run-common.sh
. "$(dirname "$0")/run-common.sh"

if pid=$(running "$APP_PID" "$APP_MATCH"); then
    if [[ -f $HEADLESS_ENV ]]; then
        say "run-headless: already running (pid $pid); use: source .run/headless.env"
        exit 0
    fi
    say "run-headless: 'make run' instance is running (pid $pid); run 'make stop' first"
    exit 1
fi
"$ROOT/scripts/stop.sh" >/dev/null

for cmd in Xvfb dbus-daemon gapplication; do
    command -v "$cmd" >/dev/null || { say "run-headless: $cmd not found (see make setup)"; exit 1; }
done
[[ -x $PYTHON ]] || { say "run-headless: $PYTHON missing, run 'make setup'"; exit 1; }

ok=0
cleanup() {
    if ((ok == 0)); then
        say "run-headless: start failed, cleaning up"
        [[ -f $APP_LOG ]] && tail -n 20 "$APP_LOG" >&2
        "$ROOT/scripts/stop.sh" >/dev/null || true
    fi
}
trap cleanup EXIT

mkdir -p "$RUN"
: >"$APP_LOG"
for dir in "$HEADLESS_HOME" "$HEADLESS_HOME"/{config,data,state,cache}; do
    mkdir -p -m 0700 "$dir"
done
# mktemp -d creates the directory with mode 0700.
runtime_dir=$(mktemp -d "${TMPDIR:-/tmp}/ai-panel-runtime.XXXXXX")
echo "$runtime_dir" >"$RUNTIME_DIR_FILE"

# --- Xvfb: -displayfd writes the chosen display number once the server accepts clients.
display_file=$RUN/xvfb.display
: >"$display_file"
setsid Xvfb -displayfd 3 -screen 0 1920x1080x24 -nolisten tcp </dev/null >"$RUN/xvfb.log" 2>&1 \
    3>"$display_file" &
echo $! >"$XVFB_PID"
deadline=$((SECONDS + 10))
until [[ -s $display_file ]]; do
    if ! kill -0 "$(cat "$XVFB_PID")" 2>/dev/null || ((SECONDS >= deadline)); then
        say "run-headless: Xvfb did not start (see $RUN/xvfb.log)"
        exit 1
    fi
    sleep 0.05
done
read -r display_number <"$display_file"
rm -f "$display_file"

# --- Environment of the bus daemon, of everything it activates and of the app.
export DISPLAY=":$display_number"
export HOME=$HEADLESS_HOME
export XDG_CONFIG_HOME=$HEADLESS_HOME/config
export XDG_DATA_HOME=$HEADLESS_HOME/data
export XDG_STATE_HOME=$HEADLESS_HOME/state
export XDG_CACHE_HOME=$HEADLESS_HOME/cache
export XDG_RUNTIME_DIR=$runtime_dir
export GIO_USE_VFS=local
export GDK_BACKEND=x11
export AI_PANEL_DEBUG=1
export WEBKIT_DISABLE_COMPOSITING_MODE=1
export LIBGL_ALWAYS_SOFTWARE=1
export NO_AT_BRIDGE=1
unset WAYLAND_DISPLAY DBUS_SESSION_BUS_ADDRESS GNOME_KEYRING_CONTROL SSH_AUTH_SOCK \
    SESSION_MANAGER XAUTHORITY AT_SPI_BUS_ADDRESS

# --- Private session bus. --fork prints the address and then the pid.
bus_out=$(dbus-daemon --session --fork --nopidfile --print-address=1 --print-pid=1 </dev/null)
DBUS_SESSION_BUS_ADDRESS=$(sed -n 1p <<<"$bus_out")
sed -n 2p <<<"$bus_out" >"$DBUS_PID"
export DBUS_SESSION_BUS_ADDRESS
[[ $DBUS_SESSION_BUS_ADDRESS == unix:* ]] || { say "run-headless: dbus-daemon failed"; exit 1; }

{
    echo "# Written by scripts/run-headless.sh; removed by make stop."
    for var in DISPLAY DBUS_SESSION_BUS_ADDRESS XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME \
        XDG_CACHE_HOME XDG_RUNTIME_DIR GIO_USE_VFS AI_PANEL_DEBUG GDK_BACKEND \
        WEBKIT_DISABLE_COMPOSITING_MODE LIBGL_ALWAYS_SOFTWARE NO_AT_BRIDGE; do
        printf 'export %s=%q\n' "$var" "${!var}"
    done
    echo "unset WAYLAND_DISPLAY"
} >"$HEADLESS_ENV"

# --- The app.
cd "$ROOT"
setsid "$PYTHON" -m app --background </dev/null >>"$APP_LOG" 2>&1 &
app_pid=$!
echo "$app_pid" >"$APP_PID"

if ! wait_ready "$app_pid" "$APP_LOG"; then
    say "run-headless: no 'ui ready' within ${READY_TIMEOUT} s"
    exit 1
fi
ok=1
say "run-headless: ui ready (pid $app_pid, DISPLAY=$DISPLAY, log $APP_LOG)"
say "run-headless: use: source .run/headless.env"
