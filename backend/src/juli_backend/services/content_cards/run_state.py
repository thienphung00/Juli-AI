"""A content run's own state and its ``content`` detail block (contract §2.1).

The state lives in the run's existing JSON column, under one key of
``workflow_runs.state`` (``content_run``). ``RunState`` keeps keys it does not
know verbatim (ADR-073 d.5), so the runner's read-modify-write cycle carries it
through every leg. It is written only:

- by ``ContentRunner`` right before the run suspends / after a leg ends (the
  runner itself is not running then), and
- by the seller-action routes while the run waits (``waiting_external``), and
  by the poll job (detection, measurement readings) when the run waits or has
  finished.

So two writers never overlap. No migration (another agent owns the chain).
"""

from __future__ import annotations

import copy as _copy
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

from juli_backend.models.models import WorkflowRun
from juli_backend.services.content_cards.constants import (
    AWAITING_CONTENT_CHOICE,
    AWAITING_CONTENT_PUBLISH,
    VIDEO,
    ContentKind,
)
from juli_backend.services.content_cards.constants import (
    CHOICE_WAIT_HOURS as CONTENT_CHOICE_WAIT_HOURS,
)
from juli_backend.services.content_cards.constants import (
    PUBLISH_WAIT_HOURS as CONTENT_PUBLISH_WAIT_HOURS,
)
from juli_backend.services.content_cards.copy import pct
from juli_backend.services.content_cards.guardrails import CHECKS_LINE_VI

STATE_KEY = "content_run"

STAGE_DRAFTING = "drafting"
STAGE_CHOICE = "choice"
STAGE_PUBLISH = "publish"
STAGE_PUBLISHED = "published"
STAGE_MEASURING = "measuring"
STAGE_FAILED = "failed"

#: Defined beside the other seller waits (``lever_flows.flows``): the runs list,
#: the decline route and the reaper read them there. 3 days / 7 days.
AWAITING_CHOICE = AWAITING_CONTENT_CHOICE
AWAITING_PUBLISH = AWAITING_CONTENT_PUBLISH
AWAITING_VALUES: frozenset[str] = frozenset({AWAITING_CHOICE, AWAITING_PUBLISH})
CHOICE_WAIT_HOURS = CONTENT_CHOICE_WAIT_HOURS
PUBLISH_WAIT_HOURS = CONTENT_PUBLISH_WAIT_HOURS

MAX_VERSIONS = 2
MODEL_STEP_RESULT = "gpt-5.4-nano · đầu ra JSON schema · đã kiểm tra"

NARRATION_CHOICE = "Đang chờ bạn xem kịch bản"
NARRATION_PUBLISH: dict[ContentKind, str] = {
    "video": "Đang chờ bạn đăng video",
    "live": "Đang chờ phiên LIVE kế tiếp",
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_state(
    kind: ContentKind, *, label: str, title: str, target: float | None, current: float | None
) -> dict[str, Any]:
    return {
        "kind": kind,
        "stage": STAGE_DRAFTING,
        "requested_version": 1,
        "drafts": [],
        "chosen_version": None,
        "chosen_at": None,
        "edited_blocks": {},
        "published_at": None,
        "published_by": None,
        "detect_rounds": 0,
        "detected": None,
        "measurement_start": None,
        "reads": {},
        "step_at": {},
        "label": label,
        "title": title,
        "target": target,
        "current": current,
        "readings": {},
    }


def state_of(run: WorkflowRun) -> dict[str, Any] | None:
    """A deep copy of the run's content state, or ``None`` for another run."""
    blob = run.state or {}
    value = blob.get(STATE_KEY) if isinstance(blob, Mapping) else None
    return _copy.deepcopy(dict(value)) if isinstance(value, Mapping) else None


def save_state(run: WorkflowRun, state: Mapping[str, Any]) -> None:
    """Write the content state back (a new dict, so the ORM sees the change)."""
    blob = dict(run.state or {})
    blob[STATE_KEY] = _copy.deepcopy(dict(state))
    run.state = blob


def draft(state: Mapping[str, Any], version: int | None = None) -> Mapping[str, Any] | None:
    drafts = [d for d in state.get("drafts") or [] if isinstance(d, Mapping)]
    if version is None:
        shown = [d for d in drafts if d.get("script")]
        return shown[-1] if shown else (drafts[-1] if drafts else None)
    return next((d for d in drafts if d.get("version") == version), None)


def shown_version(state: Mapping[str, Any]) -> int | None:
    chosen = state.get("chosen_version")
    if isinstance(chosen, int):
        return chosen
    current = draft(state)
    return int(current["version"]) if current and current.get("script") else None


# -- script blocks ------------------------------------------------------------------


def _range(t_from: Any, t_to: Any) -> str:
    def n(v: Any) -> str:
        return f"{float(v):g}" if isinstance(v, int | float) else "?"

    return f"{n(t_from)}–{n(t_to)} giây"


def script_blocks(kind: ContentKind, script: Mapping[str, Any], label: str) -> list[dict[str, str]]:
    """The four (or more) blocks the script box shows (ContentRun.dc.html)."""
    if kind == VIDEO:
        scenes = [s for s in script.get("scenes") or [] if isinstance(s, Mapping)]
        hooks = [str(h) for h in script.get("hook_options") or []]
        blocks: list[dict[str, str]] = []
        if scenes:
            first = scenes[0]
            text = (
                f"“{hooks[0]}” · {first.get('visual', '')}"
                if hooks
                else str(first.get("visual", ""))
            )
            if len(hooks) > 1:
                text += f"\nPhương án 2: “{hooks[1]}”"
            blocks.append(
                {
                    "key": "hook",
                    "label": f"Hook ({_range(first.get('t_from'), first.get('t_to'))})",
                    "text": text,
                }
            )
        for index, scene in enumerate(scenes[1:], start=2):
            lines = [
                str(scene.get("visual", "")).strip(),
                f"“{str(scene.get('voiceover', '')).strip()}”",
            ]
            if str(scene.get("on_screen", "")).strip():
                lines.append(f"Chữ: {str(scene['on_screen']).strip()}")
            blocks.append(
                {
                    "key": f"scene_{index}",
                    "label": f"Cảnh {index} ({_range(scene.get('t_from'), scene.get('t_to'))})",
                    "text": "\n".join(line for line in lines if line.strip("“” ")),
                }
            )
        tags = " ".join(str(h) for h in script.get("hashtags") or [])
        cta_lines = [f"“{script.get('cta', '')}”"]
        tail = " · ".join(x for x in (tags, str(script.get("music_hint") or "").strip()) if x)
        if tail:
            cta_lines.append(tail)
        blocks.append({"key": "cta", "label": "Kêu gọi + gợi ý", "text": "\n".join(cta_lines)})
        return blocks
    offer = script.get("offer") if isinstance(script.get("offer"), Mapping) else {}
    close = str(script.get("close", ""))
    if isinstance(offer, Mapping) and str(offer.get("text") or "").strip():
        close += f"\n{offer['text']}"
    basket = sorted(
        (b for b in script.get("basket_order") or [] if isinstance(b, Mapping)),
        key=lambda b: int(b.get("position") or 0),
    )
    order = " · ".join(
        f"{b.get('position')}. {b.get('sku')}"
        + (f" (ghim {b.get('pin_at')})" if b.get("pin_at") else "")
        for b in basket
    )
    return [
        {"key": "opening", "label": "Mở (A · Attention)", "text": str(script.get("opening", ""))},
        {"key": "show", "label": "Trình diễn (S · Show)", "text": str(script.get("show", ""))},
        {"key": "close", "label": "Chốt (B · Benefit + C · Close)", "text": close},
        {"key": "basket", "label": "Thứ tự giỏ", "text": order},
    ]


def apply_edits(blocks: list[dict[str, str]], edits: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {**block, "text": str(edits[block["key"]])}
        if isinstance(edits.get(block["key"]), str)
        else block
        for block in blocks
    ]


def plain_text(title: str, blocks: list[dict[str, str]]) -> str:
    return "\n\n".join([title, *(f"{b['label']}\n{b['text']}" for b in blocks)])


# -- the detail block -----------------------------------------------------------------


def _short(day: str | None) -> str:
    if not day or len(day) < 10:
        return "…"
    return f"{day[8:10]}/{day[5:7]}"


def _steps(kind: ContentKind, state: Mapping[str, Any]) -> list[dict[str, Any]]:
    label = str(state.get("label") or "sản phẩm")
    at = state.get("step_at") or {}
    reads = state.get("reads") or {}
    video = kind == VIDEO
    stage = state.get("stage")
    shown = draft(state)
    if shown is not None and shown.get("script"):
        draft_result: str | None = MODEL_STEP_RESULT
    elif shown is not None:
        draft_result = "Bản soạn chưa đạt kiểm tra, chưa hiển thị"
    else:
        draft_result = None
    chosen = state.get("chosen_version")
    choose_result = (
        f"Bạn chọn bản {chosen}" + (" · đã sửa" if state.get("edited_blocks") else "")
        if chosen
        else None
    )
    detected = state.get("detected") if isinstance(state.get("detected"), Mapping) else None
    if detected:
        title = detected.get("title")
        name = title.get("text") if isinstance(title, Mapping) else title
        publish_result: str | None = (
            f"{'Video mới' if video else 'Phiên'} “{name}” · {_short(detected.get('day'))}"
            if name
            else f"Đã thấy trên TikTok · {_short(detected.get('day'))}"
        )
    elif state.get("published_at"):
        publish_result = (
            f"Bạn báo đã {'đăng' if video else 'LIVE'} · {_short(str(state['published_at'])[:10])}"
        )
    else:
        publish_result = None
    start = state.get("measurement_start")
    measure_result = None
    if stage == STAGE_MEASURING and isinstance(start, str):
        if video:
            d0 = date.fromisoformat(start)
            measure_result = (
                f"Ngày 7: {_short((d0 + timedelta(days=7)).isoformat())} · "
                f"ngày 14: {_short((d0 + timedelta(days=14)).isoformat())}"
            )
        else:
            done = len((state.get("readings") or {}).get("sessions") or [])
            measure_result = f"{done}/3 phiên đã đo"
    rows = [
        (
            "read_content",
            "Đọc số liệu video và sản phẩm" if video else "Đọc số liệu các phiên LIVE",
            reads.get("performance"),
        ),
        (
            "read_product",
            "Đọc thông tin sản phẩm, từ khoá"
            if video
            else "Đọc sản phẩm, giá, khuyến mãi, Quy tắc",
            reads.get("product"),
        ),
        ("draft", "Soạn kịch bản" if video else "Soạn kịch bản host và thứ tự giỏ", draft_result),
        ("choose", "Bạn xem, sửa và chọn", choose_result),
        (
            "publish",
            f"Bạn quay và đăng video gắn {label}" if video else "Bạn LIVE theo kịch bản",
            publish_result,
        ),
        (
            "measure",
            "Đo CTR trên video mới · ngày 7, ngày 14" if video else "Đo CTOR ở 3 phiên kế tiếp",
            measure_result,
        ),
    ]
    return [
        {"key": key, "label": text, "result": result, "at": at.get(key)}
        for key, text, result in rows
    ]


def _measure_body(kind: ContentKind, state: Mapping[str, Any]) -> str:
    label = str(state.get("label") or "sản phẩm")
    readings = state.get("readings") or {}
    target = state.get("target")
    start = state.get("measurement_start")
    if kind == VIDEO:
        latest = readings.get("latest") if isinstance(readings.get("latest"), Mapping) else None
        d7 = (
            _short((date.fromisoformat(start) + timedelta(days=7)).isoformat())
            if isinstance(start, str)
            else "…"
        )
        if latest and latest.get("new_rate") is not None:
            return (
                f"CTR video mới gắn {label} sau {latest.get('days')} ngày: "
                f"{pct(latest['new_rate'])} (video cũ {pct(latest.get('old_rate'))}, "
                f"mục tiêu {pct(target)}). Kết quả ngày 7: {d7}."
            )
        return f"Juli đang chờ số liệu của video mới gắn {label}. Kết quả ngày 7: {d7}."
    sessions = [s for s in readings.get("sessions") or [] if isinstance(s, Mapping)]
    if sessions:
        last = sessions[-1]
        left = max(3 - len(sessions), 0)
        tail = f" Còn {left} phiên nữa để chốt." if left else " Đã đủ 3 phiên để chốt."
        return (
            f"Phiên {_short(last.get('day'))}: CTOR {label} {pct(last.get('ctor'))} "
            f"(trước {pct(readings.get('prior_ctor'))}, mục tiêu {pct(target)}).{tail}"
        )
    return f"Juli đo CTOR của {label} ở phiên LIVE kế tiếp có bán {label}."


def content_detail(run: WorkflowRun, *, awaiting: str | None) -> dict[str, Any] | None:
    """The contract §2.1 ``content`` block of a content run, else ``None``."""
    state = state_of(run)
    if state is None:
        return None
    kind: ContentKind = "video" if state.get("kind") == VIDEO else "live"
    video = kind == VIDEO
    label = str(state.get("label") or "sản phẩm")
    title = str(state.get("title") or label)
    stage = str(state.get("stage") or STAGE_DRAFTING)
    if run.status in ("cancelled",) and run.stop_reason == "cancelled_by_seller":
        stage = "declined"
    elif run.status in ("timed_out", "failed", "cancelled") and stage != STAGE_MEASURING:
        stage = "ended"
    elif stage == STAGE_PUBLISHED:
        stage = STAGE_PUBLISH
    elif stage == STAGE_FAILED:
        stage = "ended"
    version = shown_version(state)
    shown = draft(state, version) if version else None
    script = None
    if shown is not None and isinstance(shown.get("script"), Mapping):
        raw = dict(shown["script"])
        blocks = script_blocks(kind, raw, label)
        if state.get("chosen_version") == version:
            blocks = apply_edits(blocks, state.get("edited_blocks") or {})
        script_title = (
            "Kịch bản video 25–35 giây" if video else f"Kịch bản host cho {label} + thứ tự giỏ"
        )
        script = {
            "version": version,
            "title": script_title,
            "blocks": blocks,
            "checks": list(shown.get("checks") or []),
            "checks_line": CHECKS_LINE_VI,
            "plain_text": plain_text(f"{label} · {script_title}", blocks),
            "raw": raw,
        }
    drafts = [d for d in state.get("drafts") or [] if isinstance(d, Mapping)]
    wait = None
    if awaiting == AWAITING_PUBLISH:
        wait = {
            "title": NARRATION_PUBLISH[kind],
            "body": (
                f"Đăng video có gắn link {label} trong 7 ngày. Juli bắt đầu đo khi video mới có "
                "lượt hiển thị."
                if video
                else f"Juli đo CTOR của {label} ở 3 phiên LIVE kế tiếp có bán {label}."
            ),
            "done_label": "Tôi đã đăng video" if video else "Tôi đã LIVE xong",
            "detect_what": f"video mới gắn {label}" if video else f"phiên LIVE mới có {label}",
        }
    return {
        "kind": kind,
        "stage": stage,
        "title": f"{label} · {title} · {'kịch bản video' if video else 'kịch bản LIVE'}",
        "headline": (
            "Juli đã soạn kịch bản video, bạn quay và đăng"
            if video
            else "Juli đã soạn kịch bản host và thứ tự giỏ, bạn LIVE"
        ),
        "steps": _steps(kind, state),
        "script": script,
        "versions": len(drafts),
        "can_redraft": awaiting == AWAITING_CHOICE and len(drafts) < MAX_VERSIONS,
        "chosen_version": state.get("chosen_version"),
        "edited": bool(state.get("edited_blocks")),
        "wait": wait,
        "measure_body": _measure_body(kind, state) if stage == STAGE_MEASURING else None,
        "published_at": state.get("published_at"),
        "detected": state.get("detected"),
    }


__all__ = [
    "AWAITING_CHOICE",
    "AWAITING_PUBLISH",
    "AWAITING_VALUES",
    "CHOICE_WAIT_HOURS",
    "MAX_VERSIONS",
    "MODEL_STEP_RESULT",
    "NARRATION_CHOICE",
    "NARRATION_PUBLISH",
    "PUBLISH_WAIT_HOURS",
    "STAGE_CHOICE",
    "STAGE_DRAFTING",
    "STAGE_FAILED",
    "STAGE_MEASURING",
    "STAGE_PUBLISH",
    "STAGE_PUBLISHED",
    "STATE_KEY",
    "apply_edits",
    "content_detail",
    "draft",
    "new_state",
    "now_iso",
    "plain_text",
    "save_state",
    "script_blocks",
    "shown_version",
    "state_of",
]
