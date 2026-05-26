# Operations

This guide covers production setup and day-to-day operation for quantcheck on Linux.

## Install

```bash
git clone https://github.com/zhoucehuang-arch/quantcheck.git
cd quantcheck
bash scripts/install.sh
```

The install script creates `.venv`, installs the package in editable mode, installs Playwright Chromium, and creates `.env` from `.env.example` if needed.

## Configuration

Required:

```env
QUANTGT_EMAIL=your_quantgt_email
QUANTGT_PASSWORD=your_quantgt_password
NOTIFY_EMAIL_FILE=notify_recipients.txt
NOTIFY_ADMIN_EMAIL_FILE=notify_admin_recipients.txt
```

Recipient routing is intentionally split:

- `NOTIFY_EMAIL_TO` / `NOTIFY_EMAIL_FILE`: subscribers. They only receive successful `Quant GT Picks Updated` reports.
- `NOTIFY_ADMIN_EMAIL_TO` / `NOTIFY_ADMIN_EMAIL_FILE`: admins. They receive all operator mail, including picks updates, scrape failures, health alerts, site/function changes, official-mail check/forward failures, and full-flow test emails.

Create recipient list files with one address per line. Commas and semicolons are also accepted, and `#` starts a comment:

```text
recipient@example.com
second@example.com
# team@example.com
```

For quick one-off setups, inline recipients are still supported and are merged with the file list if both are configured:

```env
NOTIFY_EMAIL_TO=recipient@example.com,second@example.com
NOTIFY_ADMIN_EMAIL_TO=admin@example.com
```

Do not put friends or subscriber-only readers in the admin recipient list; admin mail can include tracebacks and site-change diagnostics. If admin recipients are not configured, operator alerts are logged but are not sent to subscribers.

SMTP:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USERNAME=sender@gmail.com
SMTP_PASSWORD=app_password_or_smtp_password
SMTP_FROM=sender@gmail.com
SMTP_USE_TLS=1
SMTP_STARTTLS=0
```

Gmail API:

```env
GMAIL_API_ENABLED=1
GMAIL_API_TOKEN=.config/gmail-api/token.json
GMAIL_API_FROM=sender@gmail.com
```

The Gmail token only needs this scope:

```text
https://www.googleapis.com/auth/gmail.send
```

Official Quant GT email forwarding:

```env
OFFICIAL_MAIL_ENABLED=1
OFFICIAL_MAIL_IMAP_HOST=imap.gmail.com
OFFICIAL_MAIL_IMAP_PORT=993
OFFICIAL_MAIL_IMAP_USERNAME=receiver@example.com
OFFICIAL_MAIL_IMAP_PASSWORD=app_password_or_imap_password
OFFICIAL_MAIL_IMAP_MAILBOX=INBOX
OFFICIAL_MAIL_IMAP_SEARCH=UNSEEN
```

Manually configure the Quant GT subscription mailbox to forward official emails into this IMAP inbox, then set `OFFICIAL_MAIL_ENABLED=1`. Quantcheck detects matching official mail, deduplicates it in `state/official_mail_forwarder_state.json`, and forwards it to picks-update recipients: subscribers plus admins. IMAP/check/redistribution failures go to admins only. Operator-only mail routing is unchanged.

Optional filters:

```env
OFFICIAL_MAIL_SENDER_PATTERNS=@quantgt.io,quant gt,quantgt
OFFICIAL_MAIL_SUBJECT_PATTERNS=quant gt,quantgt,picks,holdings,portfolio
OFFICIAL_MAIL_MAX_MESSAGES=20
```

Recommended permissions:

```bash
chmod 600 .env
chmod 700 .config .config/gmail-api 2>/dev/null || true
chmod 600 .config/gmail-api/token.json 2>/dev/null || true
```

## First Run

```bash
. .venv/bin/activate
python -m quantcheck.picks_check --mode baseline --force --no-random
```

Expected result: JSON output with `status: baseline_initialized`, plus `state/latest_picks.json` and `state/health.json`.

Then run:

```bash
quantcheck --once picks
quantcheck --once health_site
quantcheck --once official_mail
python -m quantcheck.picks_check --test-email
```

## systemd Deployment

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
tail -f /opt/quantcheck/logs/quantcheck_email.log
```

## Schedule

Default schedule, all in `America/New_York`:

- `08:30` picks scan
- `08:45` health + site scan
- `09:00` picks scan
- `09:20` official mail scan
- `09:40` picks scan
- `12:00` official mail scan
- `17:00` picks scan
- `17:15` health + site scan
- `17:30` official mail scan

Override with:

```env
QUANTCHECK_SCHEDULE=08:20:official_mail,08:30:picks,08:45:health_site,09:00:picks,09:20:official_mail,09:40:picks,12:00:official_mail,17:00:picks,17:15:health_site,17:30:official_mail
```

Allowed job kinds are `picks`, `health_site`, `health`, and `official_mail`.

## Runtime Files

- `state/latest_picks.json`: latest valid source state
- `state/previous_picks.json`: previous valid source state
- `state/raw/`: raw pick captures for audit
- `state/site_snapshot_latest.json`: latest site snapshot
- `state/official_mail_forwarder_state.json`: official email forwarding dedupe state
- `state/health.json`: monitor health state
- `output/`: Excel reports
- `screenshots/`: captured screenshots
- `logs/`: scheduler, monitor, health, and email logs
- `browser-profile/`: Playwright persistent login profile

## Troubleshooting

Login fails or picks table is empty:

- Confirm `QUANTGT_EMAIL` and `QUANTGT_PASSWORD`.
- Remove `browser-profile/` to force a fresh login.
- Run `python -m quantcheck.picks_check --mode screenshot --force` and inspect screenshots.

No email arrives:

- For picks-update reports, check `NOTIFY_EMAIL_FILE` / `NOTIFY_EMAIL_TO` and `NOTIFY_ADMIN_EMAIL_FILE` / `NOTIFY_ADMIN_EMAIL_TO`.
- For failures, health alerts, website changes, and test emails, check `NOTIFY_ADMIN_EMAIL_FILE` or `NOTIFY_ADMIN_EMAIL_TO`.
- For official email forwarding, check `OFFICIAL_MAIL_IMAP_*` settings and `logs/official_mail_forwarder.log`.
- Check `logs/quantcheck_email.log`.
- For Gmail API, confirm the token exists at `GMAIL_API_TOKEN` and has the `gmail.send` scope.
- For SMTP, confirm app-password requirements and TLS/STARTTLS settings.

Site-change alerts are noisy:

- Review `quantcheck/site_diff_notify.py`.
- Market Tools content is intentionally suppressed because it mostly contains external market/news churn.
- TradingView Indicator, AI Winners, and RRG are included in site snapshots so navigation/function changes are visible.

Daemon appears stuck:

- Check `logs/quantcheck_scheduler.log`.
- Check `state/quantcheck.lock`.
- Confirm `QUANTCHECK_SCAN_TIMEOUT_SECONDS` and `QUANTCHECK_HEALTH_TIMEOUT_SECONDS`.

## Safety

- Never commit `.env`, `.config/`, `browser-profile/`, output reports, screenshots, logs, or raw state.
- If credentials or tokens are exposed, rotate them immediately and delete exposed runtime files from the server.
- Failed or partial scrapes must not overwrite `state/latest_picks.json`.
- Job timeouts should be logged and contained so the daemon keeps running.
