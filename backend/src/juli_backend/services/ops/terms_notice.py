"""One-off e-mail: the terms and privacy policy changed (fast track P50-E, D68.8).

    python -m juli_backend.services.ops.terms_notice --sent-list ~/juli-terms-2026-10-27.sent
    python -m juli_backend.services.ops.terms_notice --sent-list ~/juli-terms-2026-10-27.sent --send

Operator-run only: never scheduled, not reachable over HTTP. Without ``--send`` it
is a dry run that prints counts. Recipients are the distinct non-null
``users.email`` values (case-insensitive). Sending goes through the ops SMTP mailer
(``services/ops/mailer.py``, ``OPS_SMTP_*``); ``--send`` refuses to start when
``OPS_SMTP_HOST`` is unset.

Idempotent: every address that was sent is appended (flushed per send) to the
``--sent-list`` file as a SHA-256 of the lower-cased address, never the address
itself, and a re-run skips it. A failed send is not recorded, so the next run
retries it. Keep the file until the notice is done: there is no database column
for "notice sent" (no migration for a one-off; DEBT). Output is counts only; no
address is ever printed or logged.

Env: ``DATABASE_URL``, ``OPS_SMTP_HOST`` / ``OPS_SMTP_PORT`` / ``OPS_SMTP_USER`` /
``OPS_SMTP_PASSWORD`` / ``OPS_MAIL_FROM``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from juli_backend.services.ops.mailer import Mailer

logger = logging.getLogger(__name__)

NOTICE_SUBJECT = "Juli cập nhật Điều khoản dịch vụ và Chính sách bảo mật"

NOTICE_BODY = "\n".join(
    (
        "Chào bạn,",
        "",
        "Ngày 27/10/2026, Juli đã cập nhật Điều khoản dịch vụ và Chính sách bảo mật. "
        "Bản cập nhật có hiệu lực ngay từ ngày này.",
        "",
        "Những điểm chính:",
        "- Dữ liệu Juli nhận từ sàn chỉ dùng để cung cấp dịch vụ cho chính shop của bạn. "
        "Juli không gộp dữ liệu đó với dữ liệu của shop khác, không dùng để phục vụ khách "
        "hàng khác, không bán hay chia sẻ.",
        "- Khi bạn xoá tài khoản, toàn bộ dữ liệu shop được xoá theo thời hạn trong Chính "
        "sách bảo mật.",
        "- Thông tin liên hệ của người mua không được lưu lại. "
        "Dữ liệu người mua không bao giờ được dùng để huấn luyện.",
        "- Quyền của bạn và cách từ chối nằm trong Cài đặt → Quyền riêng tư.",
        "",
        "Đọc toàn văn:",
        "Điều khoản dịch vụ: https://app-juli.com/terms",
        "Chính sách bảo mật: https://app-juli.com/privacy",
        "",
        "Nếu có câu hỏi, bạn liên hệ lienhe@app-juli.com.",
        "",
        "Juli",
        "",
    )
)


@dataclass(frozen=True)
class NoticeResult:
    recipients: int
    already_sent: int
    to_send: int
    sent: int = 0
    failed: int = 0


def address_key(email: str) -> str:
    """What the sent list stores: a hash of the normalised address, never the address."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _read_sent(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def _distinct(emails: Iterable[str | None]) -> dict[str, str]:
    """``address_key -> address`` for every non-empty address, first spelling wins."""
    out: dict[str, str] = {}
    for raw in emails:
        address = (raw or "").strip()
        if address:
            out.setdefault(address_key(address), address)
    return out


async def run_notice(
    emails: Iterable[str | None], *, mailer: Mailer, sent_list: Path, send: bool
) -> NoticeResult:
    recipients = _distinct(emails)
    done = _read_sent(sent_list)
    pending = [(key, addr) for key, addr in recipients.items() if key not in done]
    already = len(recipients) - len(pending)
    if not send:
        return NoticeResult(len(recipients), already, len(pending))

    sent = failed = 0
    sent_list.parent.mkdir(parents=True, exist_ok=True)
    with sent_list.open("a") as record:
        for key, address in pending:
            if await mailer.send_notice(to=address, subject=NOTICE_SUBJECT, body=NOTICE_BODY):
                record.write(key + "\n")
                record.flush()
                sent += 1
            else:
                failed += 1
    logger.info("terms_notice_done", extra={"sent": sent, "failed": failed})
    return NoticeResult(len(recipients), already, len(pending), sent, failed)


def print_result(result: NoticeResult, *, send: bool) -> None:
    mode = "SEND" if send else "DRY RUN (add --send to e-mail)"
    print(
        f"terms_notice {mode}: recipients={result.recipients} "
        f"already_sent={result.already_sent} to_send={result.to_send} "
        f"sent={result.sent} failed={result.failed}"
    )


async def load_recipient_emails(database_url: str) -> list[str]:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine

    from juli_backend.core.async_db import async_database_url
    from juli_backend.models.models import User

    engine = create_async_engine(async_database_url(database_url))
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(select(User.email).where(User.email.is_not(None)))
            return [row[0] for row in rows]
    finally:
        await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="terms-notice", description="E-mail the 18/10/2026 terms change (D68.8)."
    )
    parser.add_argument(
        "--sent-list",
        required=True,
        type=Path,
        help="Local file of already-sent address hashes; re-runs skip them",
    )
    parser.add_argument("--send", action="store_true", help="Actually send (default: dry run)")
    return parser


async def _main(argv: Sequence[str] | None) -> int:
    args = build_parser().parse_args(argv)
    from juli_backend.services.ops.mailer import SmtpMailer

    mailer = SmtpMailer()
    if args.send and not mailer.configured:
        raise SystemExit("OPS_SMTP_HOST is required with --send")
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    emails = await load_recipient_emails(database_url)
    result = await run_notice(
        emails, mailer=mailer, sent_list=args.sent_list.expanduser(), send=args.send
    )
    print_result(result, send=args.send)
    return 1 if result.failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main(argv))


if __name__ == "__main__":
    sys.exit(main())
