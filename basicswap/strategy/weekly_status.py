"""Weekly proof-trial status for Evan (next_steps.md #17), run by launchd.

Added 2026-09-30 when the accumulate-BTC proof trial started. Each run:
  1. syncs the fill ledger (strategy.fill_ledger) so the score is current,
  2. runs strategy.proof_report,
  3. checks that the BasicSwap node answers and exactly 2 live_maker loops run,
then writes logs/proof_trial_weekly/<date>.txt and posts a macOS notification
with the verdict line and any health problem. Read-only: it never posts,
revokes, or bids.

Scheduled by com.market_maker.proof-trial-weekly.plist (Wednesdays 09:07).
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "logs" / "proof_trial_weekly"
NODE_URL = "http://localhost:12700/json"


def _run_module(module: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", module],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=600,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _health_problems() -> list[str]:
    problems = []
    try:
        with urllib.request.urlopen(NODE_URL, timeout=15) as resp:
            if resp.status != 200:
                problems.append(f"BasicSwap node returned HTTP {resp.status}")
    except Exception as e:  # noqa: BLE001 - any failure means the node is unusable
        problems.append(f"BasicSwap node not answering ({e.__class__.__name__})")
    ps = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True)
    loops = [line for line in ps.stdout.splitlines() if "strategy.live_maker" in line and "--loop" in line]
    if len(loops) != 2:
        problems.append(f"{len(loops)} live_maker loops running (expected 2)")
    return problems


def _notify(title: str, message: str) -> None:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    subprocess.run(
        ["osascript", "-e", f'display notification "{esc(message)}" with title "{esc(title)}"'],
        capture_output=True,
    )


def main() -> int:
    ledger_rc, ledger_out = _run_module("strategy.fill_ledger")
    report_rc, report_out = _run_module("strategy.proof_report")
    problems = _health_problems()
    if ledger_rc != 0:
        problems.append(f"fill_ledger exited {ledger_rc}")
    if report_rc != 0:
        problems.append(f"proof_report exited {report_rc}")

    verdict = next((line for line in report_out.splitlines() if line.startswith("VERDICT")), "VERDICT: unavailable")
    today = dt.date.today().isoformat()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{today}.txt"
    health = "OK" if not problems else "PROBLEMS:\n  - " + "\n  - ".join(problems)
    out_path.write_text(
        f"Proof-trial weekly status, {today}\n\nHealth: {health}\n\n{report_out}\n\n"
        f"--- fill ledger (exit {ledger_rc}) ---\n{ledger_out[-3000:]}\n"
    )

    message = verdict.replace("VERDICT: ", "")
    if problems:
        message = "NEEDS ATTENTION: " + "; ".join(problems) + f" | {message}"
    _notify("market_maker proof trial", f"{message} (report: logs/proof_trial_weekly/{today}.txt)")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
