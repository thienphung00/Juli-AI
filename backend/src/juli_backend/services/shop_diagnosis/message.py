"""Draft message to the seller — ADR-108 decisions 1 and 11.

Built from the same :class:`~juli_backend.services.shop_diagnosis.report.ShopDiagnosis`
as the page. Only *Rõ* numbers are stated as facts; a *Tham khảo* number is
written only with the word "dấu hiệu"; *Chưa đủ dữ liệu* numbers are left out.
The operator edits the draft before sending (runbook step 4).
"""

from __future__ import annotations

from juli_backend.services.shop_diagnosis.channels import CHANNEL_LABELS
from juli_backend.services.shop_diagnosis.confidence import Confidence
from juli_backend.services.shop_diagnosis.config import ShopDiagnosisConfig
from juli_backend.services.shop_diagnosis.decomposition import (
    FACTOR_LABELS,
    SELF_SEARCH_SCOPE,
    FunnelComparison,
    Verdict,
)
from juli_backend.services.shop_diagnosis.render import money, pct
from juli_backend.services.shop_diagnosis.report import ShopDiagnosis

HINT = "dấu hiệu"


def _qualified(text: str, label: Confidence | None) -> str | None:
    """``text`` as a fact when Rõ, prefixed with "dấu hiệu" when Tham khảo, else nothing."""
    if label is Confidence.CLEAR:
        return text
    if label is Confidence.REFERENCE:
        if text.startswith(SELF_SEARCH_SCOPE):  # a sentence opener, not an acronym
            text = f"{SELF_SEARCH_SCOPE[0].lower()}{text[1:]}"
        return f"{HINT} {text}"
    return None


def _gmv_sentence(subject: str, comparison: FunnelComparison) -> str | None:
    share = comparison.gmv_change_share
    if share is None:
        return None
    verb = "tăng" if share >= 0 else "giảm"
    text = (
        f"GMV {subject} {verb} {pct(abs(share), 1)} "
        f"({money(comparison.prior.gmv)} → {money(comparison.last.gmv)} mỗi ngày)"
    )
    return _qualified(text, comparison.gmv_confidence)


def _factor_sentence(comparison: FunnelComparison, config: ShopDiagnosisConfig) -> str | None:
    parts = []
    for factor in comparison.factors:
        if factor.prior is None or factor.last is None or factor.prior == factor.last:
            continue
        noise = (
            factor.confidence is not Confidence.CLEAR
            and factor.prior != 0
            and abs(factor.last / factor.prior - 1) < config.noise_relative_change
        )
        verb = "gần như không đổi" if noise else ("tăng" if factor.last > factor.prior else "giảm")
        text = _qualified(f"{FACTOR_LABELS[factor.factor]} {verb}", factor.confidence)
        if text:
            parts.append(text)
    return ", ".join(parts) if parts else None


def build_message(report: ShopDiagnosis, config: ShopDiagnosisConfig | None = None) -> str:
    """Markdown draft; every number in it carries a Rõ or Tham khảo label on the page."""
    config = config or ShopDiagnosisConfig()
    w = report.windows
    lines = [
        f"# Gửi {report.shop_name or 'shop'} — tình hình 30 ngày gần đây",
        "",
        f"So sánh {w.last_first:%d/%m}–{w.last_last:%d/%m} với "
        f"{w.prior_first:%d/%m}–{w.prior_last:%d/%m}, "
        "số trung bình mỗi ngày.",
        "",
    ]
    overall = _gmv_sentence("toàn shop", report.total)
    if overall:
        lines.append(f"- {overall[0].upper()}{overall[1:]}.")
    factors = _factor_sentence(report.total, config)
    if factors:
        lines.append(f"- Theo phễu toàn shop: {factors}.")
    for row in report.channels:
        sentence = _gmv_sentence(f"kênh {CHANNEL_LABELS[row.channel]}", row.comparison)
        if sentence:
            lines.append(f"- {sentence[0].upper()}{sentence[1:]}.")
    lines += ["", "## Sản phẩm chủ lực", ""]
    for profile in report.profiles:
        title = profile.title or f"Sản phẩm {profile.rank}"
        conclusion = profile.conclusion
        if conclusion.verdict is Verdict.STORY:
            factor = conclusion.factor
            label = profile.self_search.factor(factor).confidence if factor else None
            text = _qualified(conclusion.headline, label)
            if text:
                lines.append(f"- **{title}**: {text}. Nên xem: {conclusion.look_next}.")
                continue
        if conclusion.verdict in (Verdict.STABLE, Verdict.IMPRESSIONS_ONLY):
            lines.append(f"- **{title}**: {conclusion.headline}.")
        else:
            lines.append(f"- **{title}**: chưa đủ cơ sở để kết luận, bên mình sẽ theo dõi tiếp.")
    lines += ["", "_Bản nháp — người phụ trách đọc lại và sửa trước khi gửi._", ""]
    return "\n".join(lines)
