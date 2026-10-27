"""Best-effort desktop/phone notification, shared by exolix_restock and weekly_status.

macOS: a Notification Center banner via osascript (the original behavior).
Linux (the Dell, since 2026-10-27): a Home Assistant notify call, when HA_URL,
HA_TOKEN and HA_NOTIFY_SERVICE are set (e.g. in basicswap/.env, chmod 600):

    HA_URL=http://127.0.0.1:8123
    HA_TOKEN=<long-lived access token>
    HA_NOTIFY_SERVICE=mobile_app_<phone>   # notify.<this>

Without them it only logs. Never raises: a failed notification must not change
what the caller does next (e.g. writing the Exolix halt file).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import urllib.request

log = logging.getLogger(__name__)


def notify(title: str, message: str) -> None:
    try:
        if sys.platform == "darwin":
            def esc(s: str) -> str:
                return s.replace("\\", "\\\\").replace('"', '\\"')

            subprocess.run(
                ["osascript", "-e", f'display notification "{esc(message)}" with title "{esc(title)}"'],
                capture_output=True,
            )
            return
        url, token, service = (os.environ.get(k) for k in ("HA_URL", "HA_TOKEN", "HA_NOTIFY_SERVICE"))
        if not (url and token and service):
            log.warning("notification (no HA_URL/HA_TOKEN/HA_NOTIFY_SERVICE set): %s: %s", title, message)
            return
        req = urllib.request.Request(
            f"{url.rstrip('/')}/api/services/notify/{service}",
            data=json.dumps({"title": title, "message": message}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10).close()
    except Exception as e:  # noqa: BLE001 — best effort, see module docstring
        log.warning("notification failed (%s): %s: %s", e.__class__.__name__, title, message)


if __name__ == "__main__":  # python -m strategy.notify "title" "message" (used by deploy/dell/watchdog.sh)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    notify(sys.argv[1], sys.argv[2])
