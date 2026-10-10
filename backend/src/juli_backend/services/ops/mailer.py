"""The "Mời seller" e-mail (D25.7). SMTP, configured by env; never logs the link.

``OPS_SMTP_HOST`` / ``OPS_SMTP_PORT`` (587) / ``OPS_SMTP_USER`` /
``OPS_SMTP_PASSWORD`` / ``OPS_MAIL_FROM``. With no host configured nothing is
sent and the caller hands the accept link to the staff member instead (they
forward it); the link alone cannot take a shop -- accepting requires signing in
with the invited, verified e-mail.

Supabase's built-in mailer is not used: it only sends Supabase's own auth
templates, and the backend holds no service-role key (DEBT).
"""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InviteMail:
    to: str
    shop_name: str
    accept_url: str
    keep_ops_access: bool


class Mailer(Protocol):
    async def send_invite(self, mail: InviteMail) -> bool: ...

    async def send_notice(self, *, to: str, subject: str, body: str) -> bool: ...


def invite_body(mail: InviteMail) -> str:
    keep = (
        "\nKhi nhận shop, bạn có thể đồng ý để đội ngũ Juli tiếp tục hỗ trợ vận hành "
        "(duyệt thẻ, nhập Quy tắc thay bạn). Bạn có thể từ chối.\n"
        if mail.keep_ops_access
        else ""
    )
    return (
        f"Chào bạn,\n\nĐội ngũ Juli đã kết nối shop “{mail.shop_name}” và mời bạn nhận "
        "shop về tài khoản Juli của mình. Thẻ, lượt chạy, Quy tắc và lịch sử được giữ nguyên.\n"
        f"{keep}\nNhận shop: {mail.accept_url}\n\n"
        "Đăng nhập bằng đúng địa chỉ email này. Liên kết hết hạn sau 7 ngày.\n\n— Juli"
    )


class SmtpMailer:
    def __init__(self) -> None:
        self.host = os.environ.get("OPS_SMTP_HOST", "").strip()
        self.port = int(os.environ.get("OPS_SMTP_PORT", "587") or 587)
        self.user = os.environ.get("OPS_SMTP_USER", "").strip()
        self.password = os.environ.get("OPS_SMTP_PASSWORD", "")
        self.sender = os.environ.get("OPS_MAIL_FROM", "").strip() or "Juli <no-reply@app-juli.com>"

    @property
    def configured(self) -> bool:
        return bool(self.host)

    def _send(self, mail: InviteMail) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = mail.to
        message["Subject"] = f"Nhận shop {mail.shop_name} trên Juli"
        message.set_content(invite_body(mail))
        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            smtp.starttls()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(message)

    def _send_plain(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            smtp.starttls()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(message)

    async def send_notice(self, *, to: str, subject: str, body: str) -> bool:
        if not self.configured:
            logger.info("ops_notice_mail_not_configured")
            return False
        try:
            await asyncio.to_thread(self._send_plain, to, subject, body)
        except (OSError, smtplib.SMTPException):
            logger.warning("ops_notice_mail_failed", exc_info=True)
            return False
        return True

    async def send_invite(self, mail: InviteMail) -> bool:
        if not self.configured:
            logger.info("ops_invite_mail_not_configured")
            return False
        try:
            await asyncio.to_thread(self._send, mail)
        except (OSError, smtplib.SMTPException):
            logger.warning("ops_invite_mail_failed", exc_info=True)
            return False
        logger.info("ops_invite_mail_sent")
        return True


_default: Mailer | None = None


def get_mailer() -> Mailer:
    global _default
    if _default is None:
        _default = SmtpMailer()
    return _default


def set_mailer(mailer: Mailer | None) -> None:
    """Tests inject a fake."""
    global _default
    _default = mailer
