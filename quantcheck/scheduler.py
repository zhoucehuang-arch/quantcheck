from __future__ import annotations

import argparse
import fcntl
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(os.environ.get("QUANTCHECK_HOME", Path(__file__).resolve().parents[1]))
LOGS = ROOT / "logs"
LOGS.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOGS / "quantcheck_scheduler.log"
LOCK_FILE = ROOT / "state" / "quantcheck.lock"
NY = ZoneInfo("America/New_York")

DEFAULT_SCHEDULE = [
    (8, 30, "picks"),
    (8, 45, "health_site"),
    (9, 0, "picks"),
    (9, 40, "picks"),
    (17, 0, "picks"),
    (17, 15, "health_site"),
]


def log(msg: str):
    ts = datetime.now(timezone.utc).isoformat()
    LOG_FILE.open("a", encoding="utf-8").write(f"[{ts}] {msg}\n")


def load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def parse_schedule(raw: str | None):
    if not raw:
        return DEFAULT_SCHEDULE
    out = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        hhmm, kind = item.split(":", 1)
        h, m = [int(x) for x in hhmm.split("-") if x] if "-" in hhmm else [int(x) for x in hhmm.split(":")]
        out.append((h, m, kind))
    return out or DEFAULT_SCHEDULE


def seconds_until_next(schedule):
    now = datetime.now(NY)
    candidates = []
    for h, m, kind in schedule:
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target = target.replace(day=target.day)  # placeholder; adjusted below
            from datetime import timedelta
            target = target + timedelta(days=1)
        candidates.append((target, kind))
    target, kind = min(candidates, key=lambda x: x[0])
    return max(1, int((target - now).total_seconds())), target, kind


def run_cmd(args: list[str], timeout: int) -> int:
    env = os.environ.copy()
    env.setdefault("QUANTCHECK_HOME", str(ROOT))
    start = time.time()
    try:
        p = subprocess.run(args, cwd=str(ROOT), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        if p.stdout:
            log(p.stdout[-8000:])
        log(f"command rc={p.returncode} elapsed={time.time()-start:.1f}s: {' '.join(args)}")
        return p.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        if out:
            log(out[-4000:])
        log(f"timeout after {timeout}s: {' '.join(args)}")
        return 124
    except Exception as e:
        log(f"command failed: {' '.join(args)} error={e}")
        return 1


def run_picks(force: bool = False):
    timeout = int(os.environ.get("QUANTCHECK_SCAN_TIMEOUT_SECONDS", "110"))
    args = [sys.executable, "-m", "quantcheck.picks_check", "--mode", "check", "--no-random"]
    if force:
        args.append("--force")
    return run_cmd(args, timeout)


def run_health_site():
    # Health can self-alert by email. Site snapshot errors are logged and suppressed,
    # then health keeps monitoring stale-success failures.
    timeout = int(os.environ.get("QUANTCHECK_HEALTH_TIMEOUT_SECONDS", "110"))
    rc1 = run_cmd([sys.executable, "-m", "quantcheck.health_watchdog"], timeout)
    rc2 = run_cmd([sys.executable, "-m", "quantcheck.site_snapshot"], timeout)
    rc3 = 0
    if rc2 == 0:
        rc3 = run_cmd([sys.executable, "-m", "quantcheck.site_diff_notify"], timeout)
    return max(rc1, rc2 if rc2 != 124 else 0, rc3)


def run_once(kind: str):
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log(f"skip {kind}: another run is active")
            return 0
        jitter = int(os.environ.get("QUANTCHECK_JITTER_SECONDS", "5"))
        if jitter > 0:
            time.sleep(random.randint(0, jitter))
        if kind == "picks":
            return run_picks()
        if kind == "health_site":
            return run_health_site()
        if kind == "health":
            return run_cmd([sys.executable, "-m", "quantcheck.health_watchdog"], int(os.environ.get("QUANTCHECK_HEALTH_TIMEOUT_SECONDS", "110")))
        raise SystemExit(f"unknown job kind: {kind}")


def daemon():
    load_env()
    schedule = parse_schedule(os.environ.get("QUANTCHECK_SCHEDULE"))
    stop = False
    def handler(signum, frame):
        nonlocal stop
        stop = True
        log(f"received signal {signum}; stopping")
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
    log("scheduler started")
    while not stop:
        sleep_s, target, kind = seconds_until_next(schedule)
        log(f"next {kind} at {target.isoformat()} in {sleep_s}s")
        end = time.time() + sleep_s
        while not stop and time.time() < end:
            time.sleep(min(30, end - time.time()))
        if stop:
            break
        run_once(kind)
    log("scheduler stopped")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", choices=["picks", "health_site", "health"], help="run one job then exit")
    ap.add_argument("--daemon", action="store_true", help="run built-in scheduler loop")
    args = ap.parse_args()
    load_env()
    if args.once:
        raise SystemExit(run_once(args.once))
    daemon()


if __name__ == "__main__":
    main()
