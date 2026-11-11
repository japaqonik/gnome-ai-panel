"""Exercise ``LibsecretStore`` against the Secret Service on the current session bus.

Run only by ``tests/integration/test_libsecret.py`` inside a private bus with a private
keyring daemon. Prints one JSON object with the results.
"""

import asyncio
import json
import sys

from app.config import Keyring
from app.secrets import LibsecretStore, SecretError, resolve


def main() -> int:
    name, value = sys.argv[1], sys.argv[2]
    store = LibsecretStore()
    result: dict[str, object] = {}
    try:
        store.ensure_available()
        result["has_before"] = store.has(name)
        result["get_before"] = store.get(name)
        store.set(name, value)
        result["has_after_set"] = store.has(name)
        result["get_after_set"] = store.get(name)
        # resolve() calls the blocking store from a worker thread.
        result["resolve"] = asyncio.run(resolve(Keyring(name), store=store, prompt_cb=None))
        store.set(name, value + "-2")
        result["get_after_overwrite"] = store.get(name)
        result["other_name"] = store.get(name + "-other")
        result["delete"] = store.delete(name)
        result["delete_again"] = store.delete(name)
        result["has_after_delete"] = store.has(name)
    except SecretError as exc:
        result["error"] = str(exc)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
