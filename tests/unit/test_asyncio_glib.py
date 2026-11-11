"""asyncio on the GLib main loop (PLAN §7 risk, decides plan A vs plan B).

Plan A (native ``gi.events.GLibEventLoopPolicy``) is used as long as these pass.
"""

import asyncio
import sys
import time

from gi.events import GLibEventLoop, GLibEventLoopPolicy
from gi.repository import Gio


async def _subprocess_and_sleep() -> dict:
    loop = asyncio.get_running_loop()
    proc = await asyncio.create_subprocess_exec("true")
    true_rc = await proc.wait()

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout=10)

    start = time.monotonic()
    await asyncio.sleep(0.1)
    slept = time.monotonic() - start
    return {
        "loop": loop,
        "true_rc": true_rc,
        "rc": proc.returncode,
        "out": out,
        "err": err,
        "slept": slept,
    }


def _check(result: dict) -> None:
    assert isinstance(result["loop"], GLibEventLoop)
    assert result["true_rc"] == 0
    assert result["rc"] == 3
    assert result["out"] == b"out\n"
    assert result["err"] == b"err\n"
    assert 0.09 <= result["slept"] < 2


def test_subprocess_and_sleep_on_new_glib_loop() -> None:
    with GLibEventLoopPolicy() as policy:
        loop = policy.new_event_loop()
        try:
            result = loop.run_until_complete(asyncio.wait_for(_subprocess_and_sleep(), 20))
        finally:
            loop.close()
    _check(result)


def test_subprocess_and_sleep_inside_gio_application_run() -> None:
    """The way the app uses it: ``Gio.Application.run`` drives the asyncio loop."""
    results: list[dict] = []
    errors: list[BaseException] = []

    async def job() -> None:
        try:
            results.append(await asyncio.wait_for(_subprocess_and_sleep(), 20))
        except BaseException as exc:  # reported by the assertions below
            errors.append(exc)

    # No application id: nothing is registered on D-Bus.
    app = Gio.Application(application_id=None, flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect("activate", lambda a: a.create_asyncio_task(job()))
    with GLibEventLoopPolicy():
        rc = app.run([])

    assert rc == 0
    assert errors == []
    assert len(results) == 1
    _check(results[0])
