"""P50-E (D68.8): the one-off terms-change e-mail, with the mailer mocked.

Dry run by default (counts only); never prints or logs an address; a re-run never
sends twice (local sent-list of address hashes); a failed send is retried next run.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from juli_backend.services.ops import terms_notice
from juli_backend.services.ops.terms_notice import (
    NOTICE_BODY,
    NOTICE_SUBJECT,
    run_notice,
)

EMAILS = ["lan@gmail.com", "Lan@Gmail.com ", "minh@shop.vn", "hoa@yahoo.com"]


class FakeMailer:
    def __init__(self, fail: set[str] | None = None) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.fail = fail or set()

    async def send_notice(self, *, to: str, subject: str, body: str) -> bool:
        if to in self.fail:
            return False
        self.sent.append((to, subject, body))
        return True


def test_copy_has_every_required_point_and_no_em_dash() -> None:
    text = NOTICE_SUBJECT + NOTICE_BODY
    assert "—" not in text
    for needed in (
        "Điều khoản dịch vụ",
        "Chính sách bảo mật",
        "27/10/2026",
        "có hiệu lực ngay",
        "chính shop của bạn",
        "không gộp dữ liệu đó với dữ liệu của shop khác",
        "toàn bộ dữ liệu shop được xoá",
        "Dữ liệu người mua không bao giờ được dùng để huấn luyện",
        "Cài đặt → Quyền riêng tư",
        "https://app-juli.com/terms",
        "https://app-juli.com/privacy",
        "lienhe@app-juli.com",
    ):
        assert needed in text, needed
    for retired in ("khử định danh", "điều kiện sử dụng"):
        assert retired not in text, retired


async def test_dry_run_sends_nothing_and_writes_nothing(tmp_path: Path) -> None:
    mailer = FakeMailer()
    sent_list = tmp_path / "sent.txt"
    result = await run_notice(EMAILS, mailer=mailer, sent_list=sent_list, send=False)
    assert mailer.sent == []
    assert not sent_list.exists()
    assert (result.recipients, result.already_sent, result.to_send) == (3, 0, 3)
    assert (result.sent, result.failed) == (0, 0)


async def test_send_once_per_address_and_rerun_sends_nothing(tmp_path: Path) -> None:
    mailer = FakeMailer()
    sent_list = tmp_path / "sent.txt"
    first = await run_notice(EMAILS, mailer=mailer, sent_list=sent_list, send=True)
    assert first.sent == 3 and first.failed == 0
    assert sorted(to for to, _, _ in mailer.sent) == [
        "hoa@yahoo.com",
        "lan@gmail.com",
        "minh@shop.vn",
    ]
    assert all(s == NOTICE_SUBJECT and b == NOTICE_BODY for _, s, b in mailer.sent)

    # The sent list holds hashes, never the addresses themselves.
    stored = sent_list.read_text()
    assert "@" not in stored and len(stored.split()) == 3

    again = await run_notice(EMAILS, mailer=mailer, sent_list=sent_list, send=True)
    assert (again.already_sent, again.to_send, again.sent) == (3, 0, 0)
    assert len(mailer.sent) == 3


async def test_failed_send_is_not_recorded_and_is_retried(tmp_path: Path) -> None:
    sent_list = tmp_path / "sent.txt"
    first = await run_notice(
        EMAILS, mailer=FakeMailer(fail={"minh@shop.vn"}), sent_list=sent_list, send=True
    )
    assert (first.sent, first.failed) == (2, 1)
    retry_mailer = FakeMailer()
    second = await run_notice(EMAILS, mailer=retry_mailer, sent_list=sent_list, send=True)
    assert [to for to, _, _ in retry_mailer.sent] == ["minh@shop.vn"]
    assert second.sent == 1


async def test_no_address_is_printed_or_logged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    result = await run_notice(
        EMAILS, mailer=FakeMailer(fail={"hoa@yahoo.com"}), sent_list=tmp_path / "s", send=True
    )
    terms_notice.print_result(result, send=True)
    out = capsys.readouterr().out + caplog.text
    assert "@" not in out
    assert "sent=2" in out and "failed=1" in out


def test_send_refuses_an_unconfigured_mailer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("OPS_SMTP_HOST", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match="OPS_SMTP_HOST"):
        terms_notice.main(["--sent-list", str(tmp_path / "s"), "--send"])


def test_sent_list_is_required() -> None:
    with pytest.raises(SystemExit):
        terms_notice.build_parser().parse_args([])
