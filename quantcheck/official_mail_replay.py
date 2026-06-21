from __future__ import annotations

import argparse
import json
import os

from quantcheck.config import load_env
from quantcheck.official_mail_forwarder import (
    DEFAULT_GMAIL_QUERY,
    build_forward_body,
    gmail_messages_to_official_mails,
    list_gmail_messages,
    matches_official_mail,
    split_patterns,
    DEFAULT_SENDER_PATTERNS,
    DEFAULT_SUBJECT_PATTERNS,
)
from quantcheck.notify_routes import EmailRoute, recipients_for_route
from quantcheck.gmail_api_notify import send_email_per_recipient as deliver_email


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay one historical official mail to admins only")
    parser.add_argument("--query", default="in:anywhere newer_than:365d (quantgt OR \"quant gt\" OR quantgt.io)")
    parser.add_argument("--index", type=int, default=0, help="0 = newest matched mail")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env()
    env = dict(os.environ)
    recipients = recipients_for_route(EmailRoute.ADMIN, env)
    if not recipients:
        raise RuntimeError("No admin recipients configured")

    sender_patterns = split_patterns(env.get("OFFICIAL_MAIL_SENDER_PATTERNS"), DEFAULT_SENDER_PATTERNS)
    subject_patterns = split_patterns(env.get("OFFICIAL_MAIL_SUBJECT_PATTERNS"), DEFAULT_SUBJECT_PATTERNS)
    max_messages = max(20, int(env.get("OFFICIAL_MAIL_MAX_MESSAGES") or "20"))
    query = args.query or DEFAULT_GMAIL_QUERY
    messages = list_gmail_messages(env, query, max_messages)
    if args.query:
        mails = gmail_messages_to_official_mails(messages)
    else:
        mails = [m for m in gmail_messages_to_official_mails(messages) if matches_official_mail(m, sender_patterns, subject_patterns)]
    if not mails:
        raise RuntimeError(f"No matched historical official mail found for query: {query}")
    if args.index < 0 or args.index >= len(mails):
        raise RuntimeError(f"index {args.index} out of range; matched {len(mails)} mail(s)")

    mail = mails[args.index]
    subject, body, html = build_forward_body(mail)
    result = {
        "selected_uid": mail.uid,
        "selected_subject": mail.subject,
        "selected_from": mail.from_header,
        "selected_date": mail.date,
        "matched": len(mails),
        "query": query,
        "admin_only": True,
        "dry_run": args.dry_run,
    }
    if not args.dry_run:
        delivered, failed = deliver_email(subject, body, to=recipients, html=html)
        result["delivered"] = delivered
        result["failed"] = failed
        if not delivered:
            raise RuntimeError(f"Replay delivery failed: {failed}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()