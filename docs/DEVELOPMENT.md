# Development

This guide is for maintainers changing scraper behavior, diff rules, notification delivery, or the scheduler.

## Project Structure

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
  official_mail_forwarder.py
                         IMAP detection and forwarding of official Quant GT mail
  health_watchdog.py     stale/failure health alerting
  gmail_api_notify.py    SMTP and Gmail API delivery
  recipients.py          safe CLI for subscriber/admin recipient files
scripts/
  install.sh             virtualenv install and Playwright browser install
  run-daemon.sh          local daemon launcher
systemd/
  quantcheck.service     production service unit
tests/
  test_*.py              dependency-light unit tests for core logic
```

## Local Checks

Run checks that do not need real Quant GT credentials:

```bash
python -m compileall -q quantcheck tests
python -m unittest discover -s tests -v
```

Run real-flow checks after changing selectors, login, screenshots, or notification behavior:

```bash
python -m quantcheck.picks_check --mode baseline --force --no-random
quantcheck --once picks
quantcheck --once health_site
quantcheck --once official_mail
python -m quantcheck.picks_check --test-email
```

## Design Notes

- `picks_report.py` owns Playwright scraping and Excel formatting.
- `picks_check.py` orchestrates baseline/check/test-email flows.
- `official_mail_forwarder.py` forwards matching official Quant GT emails to the same picks-update route as scraper-detected changes.
- `diff.py` should stay pure and easy to unit test.
- `validation.py` rejects logged-out demo data and incomplete row-detail captures before state writes.
- `state.py` should be used for JSON state writes so interrupted runs do not corrupt files.
- `gmail_api_notify.py` should keep Gmail API permission limited to `gmail.modify` for inbox processing, and only use `gmail.send` for the legacy outbound path when explicitly enabled.

## Scraper Maintenance

When Quant GT changes its page structure:

- Update selectors in `picks_report.py`.
- Keep authentication checks in place before accepting captured data.
- Add or update unit tests for any pure parsing, diff, or validation rule.
- Run the real-flow checks with credentials before deploying.

## Release Checklist

```bash
python -m compileall -q quantcheck tests
python -m unittest discover -s tests -v
git status --short
```

For production changes, deploy to the server, run baseline/check/test-email once, then restart the systemd service.
