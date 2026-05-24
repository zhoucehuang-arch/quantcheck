# quantcheck

Standalone Quant GT monitor for Linux. It logs in to Quant GT, captures Monthly and Weekly Picks, detects real pick changes, and sends email alerts with Excel reports and screenshots.

It replaces a Hermes CronJob-style scheduler with a small self-contained Python daemon.

## Features

- Logged-in Quant GT scraping with Playwright.
- Monthly and Weekly Picks reports as Excel files.
- Screenshot capture for changed pages.
- Diff logic that ignores market-noise fields such as price, return, market cap, and P/E.
- Guards against logged-out demo data and partial row-detail captures.
- Email delivery through SMTP or Gmail API.
- Built-in New York time scheduler, file lock, timeouts, health checks, and logs.
- Site snapshots for Quant GT Picks, TradingView Indicator, AI Winners, RRG, Market Tools, and Study Guide pages.

## Requirements

- Linux server.
- Python 3.11 or newer.
- systemd for production daemon deployment.
- Quant GT member credentials.
- SMTP credentials or a Gmail API token for email alerts.

Windows is not a supported daemon runtime.

## Quickstart

```bash
git clone https://github.com/zhoucehuang-arch/quantcheck.git
cd quantcheck
bash scripts/install.sh
. .venv/bin/activate
```

Edit `.env`:

```env
QUANTGT_EMAIL=your_quantgt_email
QUANTGT_PASSWORD=your_quantgt_password
NOTIFY_EMAIL_TO=recipient@example.com

SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USERNAME=sender@gmail.com
SMTP_PASSWORD=app_password_or_smtp_password
SMTP_FROM=sender@gmail.com
```

Initialize baseline without sending a change alert:

```bash
python -m quantcheck.picks_check --mode baseline --force --no-random
```

Run checks manually:

```bash
quantcheck --once picks
quantcheck --once health_site
```

Run continuously:

```bash
bash scripts/run-daemon.sh
```

## Common Commands

```bash
# Send a full-flow test email with Excel and screenshots.
python -m quantcheck.picks_check --test-email

# Run dependency-light local checks.
python -m compileall -q quantcheck tests
python -m unittest discover -s tests -v

# Install as a systemd service.
sudo rsync -a ./ /opt/quantcheck/
cd /opt/quantcheck
sudo bash scripts/install.sh
sudo cp systemd/quantcheck.service /etc/systemd/system/quantcheck.service
sudo systemctl daemon-reload
sudo systemctl enable --now quantcheck.service
```

## Runtime Files

- `state/`: latest/previous pick state, health state, raw audit captures, site snapshots.
- `output/`: Excel reports.
- `screenshots/`: captured screenshots.
- `logs/`: scheduler, monitor, health, and email logs.
- `browser-profile/`: Playwright persistent login profile.

These paths are ignored by git.

## Documentation

- [Operations](docs/OPERATIONS.md): production deployment, schedule, credentials, logs, and troubleshooting.
- [Development](docs/DEVELOPMENT.md): project structure, tests, and maintenance notes.

## Safety Notes

- Never commit `.env`, `.config/`, `browser-profile/`, reports, screenshots, logs, or raw state.
- Failed or partial scrapes must not overwrite `state/latest_picks.json`.
- No notification should be sent on no-change runs.
