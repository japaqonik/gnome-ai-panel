#!/usr/bin/env bash
# make stop: stop what make run / make run-headless started (PLAN, Commands).
# 1. `gapplication action pl.local.AiPanel quit` on the bus the app was started on,
# 2. after 3 s SIGTERM (then SIGKILL) to the processes recorded in .run/*.pid,
# 3. remove pid files, .run/headless.env and the temporary XDG_RUNTIME_DIR.
# Exit code 0 also when nothing is running. Only processes whose pid file and command line
# match are signalled, so a quit is never sent to an instance this script did not start.
set -uo pipefail
# shellcheck source=scripts/run-common.sh
. "$(dirname "$0")/run-common.sh"

# wait_gone <pid> <seconds>
wait_gone() {
    local pid=$1 end=$((SECONDS + $2))
    while kill -0 "$pid" 2>/dev/null; do
        ((SECONDS < end)) || return 1
        sleep 0.1
    done
}

# terminate <pidfile> <match> <name> [grace seconds before SIGTERM]
terminate() {
    local pid
    if pid=$(running "$1" "$2"); then
        if (($# > 3)) && wait_gone "$pid" "$4"; then
            :
        else
            kill -TERM "$pid" 2>/dev/null
            if ! wait_gone "$pid" 3; then
                say "stop: $3 (pid $pid) ignored SIGTERM, sending SIGKILL"
                kill -KILL "$pid" 2>/dev/null
                wait_gone "$pid" 2 || { say "stop: $3 (pid $pid) is still running"; failed=1; }
            fi
        fi
        say "stop: $3 stopped (pid $pid)"
    fi
    rm -f "$1"
}

failed=0

if pid=$(running "$APP_PID" "$APP_MATCH"); then
    if [[ -f $HEADLESS_ENV ]]; then
        # shellcheck disable=SC1090
        (. "$HEADLESS_ENV" && timeout 5 gapplication action pl.local.AiPanel quit) || true
    else
        timeout 5 gapplication action pl.local.AiPanel quit || true
    fi
fi
terminate "$APP_PID" "$APP_MATCH" "app" 3
terminate "$DBUS_PID" "$DBUS_MATCH" "dbus-daemon"
terminate "$XVFB_PID" "$XVFB_MATCH" "Xvfb"

if [[ -f $RUNTIME_DIR_FILE ]]; then
    read -r runtime_dir <"$RUNTIME_DIR_FILE" || true
    # Only remove what run-headless.sh created with mktemp.
    if [[ ${runtime_dir:-} == */ai-panel-runtime.* && -d $runtime_dir && ! -L $runtime_dir ]]; then
        # xdg-document-portal mounts $XDG_RUNTIME_DIR/doc (FUSE, auto_unmount); it goes away
        # when the bus is gone. Never descend into a mount that is still there.
        for _ in {1..20}; do
            mountpoint -q "$runtime_dir/doc" 2>/dev/null || break
            sleep 0.1
        done
        mountpoint -q "$runtime_dir/doc" 2>/dev/null && fusermount3 -u "$runtime_dir/doc" 2>/dev/null
        rm -rf --one-file-system -- "$runtime_dir"
    fi
    rm -f "$RUNTIME_DIR_FILE"
fi
rm -f "$HEADLESS_ENV" "$RUN/xvfb.display"
exit "$failed"
