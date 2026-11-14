"""Sending the stock e-mail (Part S): the Ops SMTP settings (``services/ops/mailer``), HTML + text.

``OPS_SMTP_HOST`` / ``OPS_SMTP_PORT`` / ``OPS_SMTP_USER`` / ``OPS_SMTP_PASSWORD`` /
``OPS_MAIL_FROM``. With no host nothing is sent and the job logs it. Never logs an address or a
link. Tests inject a fake (:func:`set_stock_mailer`).
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from collections.abc import Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from juli_backend.services.ops.mailer import SmtpMailer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StockMail:
    to: str
    subject: str
    text: str
    html: str
    bcc: tuple[str, ...] = ()


class StockMailer(Protocol):
    @property
    def configured(self) -> bool: ...

    async def send(self, mail: StockMail) -> bool: ...


def message_of(mail: StockMail, sender: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = mail.to
    if mail.bcc:
        message["Bcc"] = ", ".join(mail.bcc)
    message["Subject"] = mail.subject
    message.set_content(mail.text)
    message.add_alternative(mail.html, subtype="html")
    return message


class SmtpStockMailer:
    def __init__(self) -> None:
        self._smtp = SmtpMailer()

    @property
    def configured(self) -> bool:
        return self._smtp.configured

    def _send(self, mail: StockMail) -> None:
        s = self._smtp
        with smtplib.SMTP(s.host, s.port, timeout=15) as smtp:
            smtp.starttls()
            if s.user:
                smtp.login(s.user, s.password)
            smtp.send_message(message_of(mail, s.sender))

    async def send(self, mail: StockMail) -> bool:
        if not self.configured:
            logger.info("stock_alert_mail_not_configured")
            return False
        try:
            await asyncio.to_thread(self._send, mail)
        except (OSError, smtplib.SMTPException):
            logger.warning("stock_alert_mail_failed", exc_info=True)
            return False
        return True


_default: StockMailer | None = None


def get_stock_mailer() -> StockMailer:
    global _default
    if _default is None:
        _default = SmtpStockMailer()
    return _default


def set_stock_mailer(mailer: StockMailer | None) -> None:
    global _default
    _default = mailer


async def send_all(mailer: StockMailer, mails: Sequence[StockMail]) -> int:
    sent = 0
    for m in mails:
        if await mailer.send(m):
            sent += 1
    return sent


__all__ = [
    "SmtpStockMailer",
    "StockMail",
    "StockMailer",
    "get_stock_mailer",
    "message_of",
    "send_all",
    "set_stock_mailer",
]
