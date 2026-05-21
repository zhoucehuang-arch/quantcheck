# quantcheck

Standalone Quant GT monitor for Linux. It logs in to Quant GT, captures Monthly and Weekly Picks, writes Excel reports and screenshots, detects real pick changes, and sends email alerts without depending on Hermes CronJob or any Hermes service.

## What it does

- Scrapes logged-in Quant GT member pages with Playwright.
- Rejects logged-out demo data and partial row-detail captures before they can overwrite state.
- Ignores noisy market fields such as current price, return, market cap, and P/E when deciding whether to alert.
- Writes timestamped raw JSON, Excel reports, screenshots, health state, and logs.
- Runs as a daemon with a built-in New York time schedule, a file lock, timeouts, retries through systemd restart policy, and health alerts.
- Watches Quant GT navigation/function changes separately from pick changes.

## Supported environment

- Linux server with Python 3.11 or newer.
- systemd for continuous deployment.
- A Quant GT account with access to Monthly and Weekly Picks.
- SMTP credentials or a Gmail API token for alert email.

Windows is not a supported runtime target for the daemon because the scheduler uses Linux file locking and deployment scripts are bash/systemd based.

## Project layout

```text
quantcheck/
  config.py              .env and path handling
  state.py               atomic JSON writes and retention pruning
  diff.py                pick diff logic and analyst-signal thresholds
  validation.py          member-data and demo-data guards
  schedule.py            daemon schedule parsing
  picks_report.py        Playwright scrape and Excel export
  picks_check.py         pick monitor orchestration
  site_snapshot.py       authenticated site snapshot capture
  site_diff_notify.py    site-change diff and alerting
  health_watchdog.py     stale/failure health alerting
  gmail_api_notify.py    SMTP and Gmail API delivery
scripts/
  install.sh             virtualenv install and Playwright browser install
  run-daemon.sh          local daemon launcher
systemd/
  quantcheck.service     production service unit
tests/
  test_*.py              dependency-light unit tests for core logic
```

## Install

```bash
git clone https://github.com/zhoucehuang-arch/quantcheck.git
cd quantcheck
bash scripts/install.sh
```

The install script creates `.venv`, installs the package in editable mode, installs Playwright Chromium, and creates `.env` from `.env.example` if needed.

## Configure

Edit `.env`:

```env
QUANTGT_EMAIL=your_quantgt_email
QUANTGT_PASSWORD=your_quantgt_password
NOTIFY_EMAIL_TO=recipient@example.com
```

For SMTP:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USERNAME=sender@gmail.com
SMTP_PASSWORD=app_password_or_smtp_password
SMTP_FROM=sender@gmail.com
SMTP_USE_TLS=1
SMTP_STARTTLS=0
```

For Gmail API sending:

```env
GMAIL_API_ENABLED=1
GMAIL_API_TOKEN=.config/gmail-api/token.json
GMAIL_API_FROM=sender@gmail.com
```

The Gmail token only needs the `https://www.googleapis.com/auth/gmail.send` scope.

Recommended permissions:

```bash
chmod 600 .env
chmod 700 .config .config/gmail-api 2>/dev/null || true
chmod 600 .config/gmail-api/token.json 2>/dev/null || true
```

## Run once

Activate the environment:

```bash
. .venv/bin/activate
```

Initialize baseline without sending a change alert:

```bash
python -m quantcheck.picks_check --mode baseline --force --no-random
```

Expected result: JSON output with `status: baseline_initialized`, Monthly date, and Weekly date. It should also create `state/latest_picks.json` and `state/health.json`.

Run a manual picks check:

```bash
quantcheck --once picks
```

Run health and site checks:

```bash
quantcheck --once health_site
```

Send a full-flow test email with Excel and screenshots:

```bash
python -m quantcheck.picks_check --test-email
```

## Run continuously

Local foreground daemon:

```bash
bash scripts/run-daemon.sh
```

Production systemd deployment:

```bash
sudo mkdir -p /opt/quantcheck
sudo rsync -a ./ /opt/quantcheck/
cd /opt/quantcheck
sudo bash scripts/install.sh
sudo cp systemd/quantcheck.service /etc/systemd/system/quantcheck.service
sudo systemctl daemon-reload
sudo systemctl enable --now quantcheck.service
sudo systemctl status quantcheck.service
```

Follow logs:

```bash
journalctl -u quantcheck.service -f
tail -f /opt/quantcheck/logs/quantcheck_scheduler.log
tail -f /opt/quantcheck/logs/quantgt_monitor.log
```

## Schedule

Default schedule, all in `America/New_York`:

- `08:30` picks scan
- `08:45` health + site scan
- `09:00` picks scan
- `09:40` picks scan
- `17:00` picks scan
- `17:15` health + site scan

Override with:

```env
QUANTCHECK_SCHEDULE=08:30:picks,08:45:health_site,09:00:picks,09:40:picks,17:00:picks,17:15:health_site
```

Allowed job kinds are `picks`, `health_site`, and `health`.

## Runtime files

- `state/latest_picks.json`: latest valid source state
- `state/previous_picks.json`: previous valid source state
- `state/raw/`: raw pick captures for audit
- `state/site_snapshot_latest.json`: latest site snapshot
- `state/health.json`: monitor health state
- `output/`: Excel reports
- `screenshots/`: captured screenshots
- `logs/`: scheduler, monitor, health, and email logs
- `browser-profile/`: Playwright persistent login profile

These paths are ignored by git.

## Maintenance checks

Run dependency-light checks:

```bash
python -m compileall -q quantcheck tests
python -m unittest discover -s tests -v
```

After changing scraper selectors or login behavior, run with real credentials:

```bash
python -m quantcheck.picks_check --mode baseline --force --no-random
quantcheck --once picks
quantcheck --once health_site
python -m quantcheck.picks_check --test-email
```

## Troubleshooting

Login fails or picks table is empty:

- Confirm `QUANTGT_EMAIL` and `QUANTGT_PASSWORD`.
- Remove `browser-profile/` to force a fresh login.
- Run `python -m quantcheck.picks_check --mode screenshot --force` and inspect screenshots.

No email arrives:

- Check `NOTIFY_EMAIL_TO`.
- Check `logs/quantcheck_email.log`.
- For Gmail API, confirm the token exists at `GMAIL_API_TOKEN` and has the `gmail.send` scope.
- For SMTP, confirm app-password requirements and TLS/STARTTLS settings.

Site-change alerts are noisy:

- Review `quantcheck/site_diff_notify.py`.
- Market Tools content is intentionally suppressed because it mostly contains external market/news churn.

Daemon appears stuck:

- Check `logs/quantcheck_scheduler.log`.
- Check `state/quantcheck.lock`.
- Confirm `QUANTCHECK_SCAN_TIMEOUT_SECONDS` and `QUANTCHECK_HEALTH_TIMEOUT_SECONDS`.

## Safety rules

- Never commit `.env`, `.config/`, `browser-profile/`, output reports, screenshots, logs, or raw state.
- Failed or partial scrapes must not overwrite `state/latest_picks.json`.
- No notification should be sent on no-change runs.
- Job timeouts should be logged and contained so the daemon keeps running.
- If credentials or tokens are exposed, rotate them immediately and delete the exposed runtime files from the server.
