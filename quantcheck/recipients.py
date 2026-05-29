from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from quantcheck.config import get_root, load_env

EMAIL_RE = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$", re.IGNORECASE)
ROLE_SETTINGS = {
    "subscriber": ("NOTIFY_EMAIL_FILE", "NOTIFY_EMAIL_TO", "Quant GT ordinary subscriber recipients"),
    "admin": ("NOTIFY_ADMIN_EMAIL_FILE", "NOTIFY_ADMIN_EMAIL_TO", "Quant GT admin recipients"),
}


@dataclass(frozen=True)
class RecipientFile:
    role: str
    path: Path
    inline: list[str]
    entries: list[str]
    invalid: list[str]


def split_recipients(values: Iterable[str] | str | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        chunks = [values]
    else:
        chunks = [str(value) for value in values]
    recipients: list[str] = []
    for chunk in chunks:
        for item in chunk.replace(";", ",").split(","):
            value = item.strip()
            if value:
                recipients.append(value)
    return recipients


def normalize_email(value: str) -> str:
    return value.strip().lower()


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_RE.fullmatch(value.strip()))


def unique_emails(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        email = normalize_email(value)
        if not email or email in seen:
            continue
        out.append(email)
        seen.add(email)
    return out


def resolve_recipient_path(env: Mapping[str, str], role: str, root: Path) -> Path:
    file_key, _, _ = ROLE_SETTINGS[role]
    configured = str(env.get(file_key) or "").strip()
    if configured:
        path = Path(configured)
    else:
        path = root / ("notify_admin_recipients.txt" if role == "admin" else "notify_recipients.txt")
    if not path.is_absolute():
        path = root / path
    return path


def read_recipient_lines(path: Path) -> tuple[list[str], list[str]]:
    entries: list[str] = []
    invalid: list[str] = []
    if not path.exists():
        return entries, invalid
    for line in path.read_text(encoding="utf-8").splitlines():
        body = line.split("#", 1)[0].strip()
        if not body:
            continue
        for item in split_recipients(body):
            email = normalize_email(item)
            if is_valid_email(email):
                entries.append(email)
            else:
                invalid.append(item.strip())
    return unique_emails(entries), invalid


def load_recipient_file(env: Mapping[str, str], role: str, root: Path) -> RecipientFile:
    _, inline_key, _ = ROLE_SETTINGS[role]
    path = resolve_recipient_path(env, role, root)
    entries, invalid = read_recipient_lines(path)
    inline = unique_emails(email for email in split_recipients(env.get(inline_key, "")) if is_valid_email(email))
    return RecipientFile(role=role, path=path, inline=inline, entries=entries, invalid=invalid)


def default_header(role: str) -> str:
    _, _, title = ROLE_SETTINGS[role]
    return f"# {title}\n# Managed by quantcheck-recipients. One email per line; comments are ignored.\n\n"


def write_recipient_file(recipient_file: RecipientFile, entries: Sequence[str], *, dry_run: bool = False, backup: bool = True) -> Path | None:
    content = default_header(recipient_file.role) + "\n".join(entries) + ("\n" if entries else "")
    if dry_run:
        return None
    recipient_file.path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    if backup and recipient_file.path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = recipient_file.path.with_name(f"{recipient_file.path.name}.{stamp}.bak")
        shutil.copy2(recipient_file.path, backup_path)
    recipient_file.path.write_text(content, encoding="utf-8")
    return backup_path


def format_role(role: str) -> str:
    return "admins" if role == "admin" else "subscribers"


def print_role(recipient_file: RecipientFile) -> None:
    print(f"{format_role(recipient_file.role)} file: {recipient_file.path}")
    print(f"file recipients: {len(recipient_file.entries)}")
    for email in recipient_file.entries:
        print(f"  {email}")
    if recipient_file.inline:
        print(f"inline recipients from .env: {len(recipient_file.inline)}")
        for email in recipient_file.inline:
            print(f"  {email}")
    if recipient_file.invalid:
        print(f"invalid entries ignored: {len(recipient_file.invalid)}")
        for value in recipient_file.invalid:
            print(f"  {value}")


def route_counts(env: Mapping[str, str], root: Path) -> tuple[int, int]:
    subscribers = load_recipient_file(env, "subscriber", root)
    admins = load_recipient_file(env, "admin", root)
    subscriber_all = unique_emails([*subscribers.inline, *subscribers.entries])
    admin_all = unique_emails([*admins.inline, *admins.entries])
    picks_update = unique_emails([*subscriber_all, *admin_all])
    return len(picks_update), len(admin_all)


def command_list(args: argparse.Namespace, env: Mapping[str, str], root: Path) -> int:
    roles = [args.role] if args.role != "all" else ["subscriber", "admin"]
    for index, role in enumerate(roles):
        if index:
            print("")
        print_role(load_recipient_file(env, role, root))
    print("")
    picks_total, admin_total = route_counts(env, root)
    print(f"picks-update route total: {picks_total}")
    print(f"admin route total: {admin_total}")
    return 0


def command_check(args: argparse.Namespace, env: Mapping[str, str], root: Path) -> int:
    failed = False
    for role in ["subscriber", "admin"]:
        recipient_file = load_recipient_file(env, role, root)
        duplicate_count = max(0, len(read_raw_file_emails(recipient_file.path)) - len(recipient_file.entries))
        print(f"{format_role(role)}: {len(recipient_file.entries)} file recipients, {len(recipient_file.inline)} inline recipients")
        print(f"  file: {recipient_file.path}")
        if duplicate_count:
            print(f"  duplicates ignored: {duplicate_count}")
        if recipient_file.invalid:
            failed = True
            print(f"  invalid entries: {', '.join(recipient_file.invalid)}")
    picks_total, admin_total = route_counts(env, root)
    print(f"picks-update route total: {picks_total}")
    print(f"admin route total: {admin_total}")
    return 1 if failed else 0


def read_raw_file_emails(path: Path) -> list[str]:
    if not path.exists():
        return []
    values: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        body = line.split("#", 1)[0].strip()
        values.extend(split_recipients(body))
    return [normalize_email(value) for value in values if value.strip()]


def valid_or_exit(emails: Sequence[str]) -> list[str]:
    normalized = unique_emails(emails)
    invalid = [email for email in normalized if not is_valid_email(email)]
    if invalid:
        raise ValueError("invalid email address(es): " + ", ".join(invalid))
    return normalized


def command_add(args: argparse.Namespace, env: Mapping[str, str], root: Path) -> int:
    emails = valid_or_exit(args.emails)
    recipient_file = load_recipient_file(env, args.role, root)
    existing = set(recipient_file.entries)
    added = [email for email in emails if email not in existing]
    entries = unique_emails([*recipient_file.entries, *added])
    backup_path = write_recipient_file(recipient_file, entries, dry_run=args.dry_run, backup=not args.no_backup)
    prefix = "would add" if args.dry_run else "added"
    print(f"{prefix} {len(added)} {format_role(args.role)} recipient(s): {', '.join(added) if added else 'none'}")
    print(f"total file recipients: {len(entries)}")
    print(f"file: {recipient_file.path}")
    if backup_path:
        print(f"backup: {backup_path}")
    return 0


def command_remove(args: argparse.Namespace, env: Mapping[str, str], root: Path) -> int:
    emails = valid_or_exit(args.emails)
    recipient_file = load_recipient_file(env, args.role, root)
    remove_set = set(emails)
    removed = [email for email in recipient_file.entries if email in remove_set]
    entries = [email for email in recipient_file.entries if email not in remove_set]
    backup_path = write_recipient_file(recipient_file, entries, dry_run=args.dry_run, backup=not args.no_backup)
    prefix = "would remove" if args.dry_run else "removed"
    print(f"{prefix} {len(removed)} {format_role(args.role)} recipient(s): {', '.join(removed) if removed else 'none'}")
    print(f"total file recipients: {len(entries)}")
    print(f"file: {recipient_file.path}")
    missing = [email for email in emails if email not in set(removed)]
    if missing:
        print(f"not present: {', '.join(missing)}")
    if backup_path:
        print(f"backup: {backup_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Quant GT notification recipient files safely.")
    parser.add_argument("--root", type=Path, default=None, help="Quantcheck root directory. Defaults to QUANTCHECK_HOME or the project root.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="Show configured recipients and route totals.")
    list_parser.add_argument("--role", choices=["subscriber", "admin", "all"], default="all")

    check_parser = sub.add_parser("check", help="Validate recipient files and show route totals.")
    check_parser.set_defaults(func=command_check)

    for name, help_text in [("add", "Add recipients to a role file."), ("remove", "Remove recipients from a role file.")]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--role", choices=["subscriber", "admin"], default="subscriber")
        p.add_argument("--dry-run", action="store_true", help="Preview changes without writing files.")
        p.add_argument("--no-backup", action="store_true", help="Do not create a timestamped .bak file before writing.")
        p.add_argument("emails", nargs="+", help="Email addresses. Commas and semicolons are accepted.")
        p.set_defaults(func=command_add if name == "add" else command_remove)

    list_parser.set_defaults(func=command_list)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.root or get_root()
    env = load_env(root, override=True)
    try:
        return args.func(args, env, root)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
