# quantcheck

Standalone Quant GT monitor. It does not require Hermes CronJob or any Hermes tool.

It can:

1. log in to Quant GT and collect Monthly/Weekly Picks from member pages;
2. generate timestamped Excel reports and screenshots;
3. detect real changes only;
4. send email alerts with report/screenshot attachments;
5. run continuously with its own scheduler, lock, timeout, retry/health checks, and logs.

## Current workflow summary

The old deployment used Hermes CronJob only as the scheduler. The real business logic was already in Python scripts:

- `quantcheck.picks_check`
  - trading-window aware check at 08:30, 09:00, 09:40, 17:00 New York time;
  - validates logged-in member data;
  - ignores market-noise fields such as current price/return/market cap/P/E;
  - rejects demo/logged-out Weekly Picks;
  - rejects partial row-detail captures before they poison state;
  - compares with previous valid state;
  - only on real diff: writes raw JSON, creates Excel, captures screenshots, sends email.

- `quantcheck.picks_report`
  - fetches fresh Quant GT data with Playwright;
  - expands rows for detail fields;
  - writes source-faithful Excel with white body cells and light green headers;
  - no inferred KPI cards and no Raw Data sheet.

- `quantcheck.health_watchdog`
  - watches `state/health.json`;
  - sends health email if consecutive failures or stale success is detected.

- `quantcheck.site_snapshot` and `quantcheck.site_diff_notify`
  - monitor Quant GT-owned navigation/function changes;
  - suppress page-timeout and external market-news churn.

- `quantcheck.scheduler`
  - replaces Hermes CronJob;
  - built-in daemon loop in America/New_York time;
  - uses file lock to avoid overlap;
  - wraps jobs with timeouts so hangs do not crash the daemon;
  - logs failures and lets health checks alert by email.

## Install

```bash
git clone https://github.com/<your-user>/quantcheck.git
cd quantcheck
bash scripts/install.sh
cp .env.example .env
nano .env
```

Then fill `.env` with your Quant GT login and email sender settings.

## Required config

```env
QUANTGT_EMAIL=your_quantgt_email
QUANTGT_PASSWORD=your_quantgt_password
NOTIFY_EMAIL_TO=recipient@example.com
```

For SMTP email:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USERNAME=sender@gmail.com
SMTP_PASSWORD=app_password_or_smtp_password
SMTP_FROM=sender@gmail.com
```

Optional Gmail API sending is also supported through `GMAIL_API_ENABLED=1` and `GMAIL_API_TOKEN`.
No real credentials are stored in this repository.

## Run once

Initialize baseline without alerting:

```bash
. .venv/bin/activate
python -m quantcheck.picks_check --mode baseline --force --no-random
```

Run a manual check:

```bash
quantcheck --once picks
```

Run health + site check:

```bash
quantcheck --once health_site
```

## Run continuously without Hermes

```bash
bash scripts/run-daemon.sh
```

Or with systemd:

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

## Default schedule

All times are America/New_York:

- 08:30 picks scan
- 08:45 health + site scan
- 09:00 picks scan
- 09:40 picks scan
- 17:00 picks scan
- 17:15 health + site scan

Customize with:

```env
QUANTCHECK_SCHEDULE=08:30:picks,08:45:health_site,09:00:picks,09:40:picks,17:00:picks,17:15:health_site
```

## Runtime files

- `state/latest_picks.json` latest valid source state
- `state/raw/` audit raw captures
- `state/health.json` run health
- `output/` Excel reports
- `screenshots/` captured screenshots
- `logs/` service and monitor logs
- `browser-profile/` Playwright persistent login profile

These are ignored by git.

## Safety rules

- No `.env`, browser profile, Gmail token, output reports, screenshots, logs, or raw state should be committed.
- No notification is sent on no-change runs.
- A failed/partial scrape should not overwrite good state.
- A timeout is logged and suppressed at job level; the daemon continues running.
