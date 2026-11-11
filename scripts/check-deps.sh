#!/usr/bin/env bash
# Checks system dependencies that need sudo to install (PLAN §1).
# Exit 0 when everything is present; otherwise prints the apt command and exits 1.
set -u

missing=()
add() {
    local pkg
    for pkg in "$@"; do
        [[ " ${missing[*]-} " == *" $pkg "* ]] || missing+=("$pkg")
    done
}
need_cmd() { # need_cmd <command> <apt package...>
    local cmd=$1
    shift
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "brak: $cmd" >&2
        add "$@"
    fi
}

need_cmd python3 python3
need_cmd Xvfb xvfb
need_cmd xvfb-run xvfb
need_cmd gjs gjs
need_cmd node nodejs
need_cmd npm npm
need_cmd glib-compile-schemas libglib2.0-bin

if command -v python3 >/dev/null 2>&1; then
    if ! python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
        echo "brak: python3 venv/ensurepip" >&2
        add python3-venv
    fi
    if ! python3 -c 'import gi' >/dev/null 2>&1; then
        echo "brak: PyGObject (gi)" >&2
        add python3-gi gir1.2-webkit-6.0
    elif ! python3 -c 'import gi; gi.require_version("WebKit", "6.0")' >/dev/null 2>&1; then
        echo "brak: WebKit 6.0 GObject introspection" >&2
        add gir1.2-webkit-6.0
    fi
fi

if ((${#missing[@]})); then
    echo "Brakuje pakietów systemowych. Zainstaluj je poleceniem:" >&2
    echo "sudo apt install ${missing[*]}"
    exit 1
fi
echo "check-deps: ok"
