"""Cài đặt › Đề xuất kế hoạch: preview and apply a planned-changes file (P91 D-13).

``preview`` reads the ``.xlsx`` and checks every row on its own (``rows.check_rows``), builds
the card each valid row would become, and writes nothing. ``apply`` re-reads the same file
(nothing is kept between calls), and for each valid row, dependencies first:

1. saves a **manual card** with ``origin = "import"`` through ``manual.create_manual`` (JC code,
   queue, ``external_ref``), carrying the row's reason, chi phí, measurement window and
   ``depends_on`` (ref and code);
2. sends it, then records the shop's decision (đồng ý / không đồng ý / đề xuất chỉnh sửa);
3. for a row whose status is "hoàn thành", records the execution **at the date in the file**
   (event and execution backdated, actor = the importer). Such an execution carries
   ``readback = False``: the Connector has nothing "after" to read, the history is the baseline.

A ref imported before is never duplicated: same content and state = unchanged; a later state
(decision, "đang", "hoàn thành") is carried forward; changed content is refused (use a new ref).
Each applied file is a numbered version (who, when, why, file hash, per-row outcome).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_events import (
    ACTOR_SELLER,
    EVENT_ACCEPTED,
    EVENT_DISMISSED,
    EVENT_EDITED,
)
from juli_backend.models.planned_changes import PlannedChangeImport, PlannedChangeRef
from juli_backend.models.shop_proposals import (
    STATUS_APPROVED,
    STATUS_CHANGES_REQUESTED,
    STATUS_DRAFT,
    STATUS_REJECTED,
    ShopProposal,
    ShopProposalExecution,
)
from juli_backend.services.card_events import keys
from juli_backend.services.planned_changes import rows as pr
from juli_backend.services.shop_inputs import xlsx_io
from juli_backend.services.shop_proposals import cycle as proposals
from juli_backend.services.shop_proposals.cycle import ProposalError
from juli_backend.services.shopee_recommendations import config, manual, store
from juli_backend.services.shopee_recommendations import listing as lst
from juli_backend.services.shopee_recommendations import service as reco_service
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.evaluate import evaluate
from juli_backend.services.shopee_recommendations.kinds import spec
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.model import Candidate

ORIGIN_IMPORT = "import"
SUGGESTED_REASONS: tuple[str, ...] = (
    "Kế hoạch tháng này",
    "Cập nhật tiến độ",
    "Bổ sung thay đổi",
    "Khác",
)
MAX_REASON_CHARS = 500
MAX_FILE_BYTES = xlsx_io.MAX_FILE_BYTES

ERROR_NO_DATA = "planned_no_data"
ERROR_FILE = "planned_invalid_file"
ERROR_MISMATCH = "planned_file_changed"
ERROR_NOTHING = "planned_nothing_to_apply"
ERROR_REASON = "planned_invalid_reason"


class ImportFileError(ValueError):
    """The file cannot be read as the planned-changes sheet at all."""


class FileMismatch(ValueError):
    """The file sent to apply is not the one that was checked."""


class NothingToApply(ValueError):
    """The file holds no valid row that changes anything."""


@dataclass(frozen=True)
class Actor:
    """Who imports: ``seller`` (Demo, ``user_id``) or ``staff`` (Ops, ``staff_id``)."""

    kind: str
    user_id: uuid.UUID | None = None
    staff_id: uuid.UUID | None = None

    @property
    def set_by(self) -> str:
        return "seller" if self.kind == "seller" else "staff"

    def manual(self) -> manual.Actor:
        who = self.user_id if self.kind == "seller" else self.staff_id
        assert who is not None
        return manual.Actor(self.kind, who, staff_id=self.staff_id)


@dataclass
class RowPlan:
    row: pr.PlannedRow
    action: str  # create | advance | unchanged | rejected
    problems: list[pr.Problem] = field(default_factory=list)
    warnings: list[pr.Problem] = field(default_factory=list)
    card: dict[str, Any] | None = None
    prior_card_id: uuid.UUID | None = None


@dataclass
class Preview:
    file_hash: str
    plans: list[RowPlan]
    order: list[str]
    missing_columns: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        c = {"rows": len(self.plans), "create": 0, "advance": 0, "unchanged": 0, "rejected": 0}
        for p in self.plans:
            c[p.action] += 1
        c["warnings"] = sum(len(p.warnings) for p in self.plans)
        return c


@dataclass
class ApplyResult:
    number: int
    file_hash: str
    reason: str
    applied_at: datetime
    created: int
    advanced: int
    executed: int
    unchanged: int
    rejected: int
    rows: list[dict[str, Any]]


# ------------------------------------------------------------------------------ template


def build_template() -> bytes:
    """The empty sheet with the column headers and two invented example rows."""
    head = [label for _, label, _ in pr.COLUMNS]
    sample: list[list[xlsx_io.Cell]] = [
        [
            "TD1", "1001", "Sửa tên sản phẩm", "Tên cũ của sản phẩm mẫu",
            "Tên mới của sản phẩm mẫu", "Đưa từ khoá chính lên đầu", 0, "05/11/2026", 14, "",
            "đồng ý", "chưa",
        ],
        [
            "AN1", "1002", "Ẩn sản phẩm", "", "", "Gộp vào sản phẩm TD1 rồi ẩn bản cũ",
            0, "12/11/2026", 7, "TD1", "", "chưa",
        ],
    ]  # fmt: skip
    notes = [
        ["Cột", "Cách điền"],
        ["Mã (ref)", "Mã riêng của bạn cho từng dòng, ví dụ TD1, XM3. Không trùng nhau."],
        ["Mã sản phẩm", "Mã sản phẩm Shopee (item id)."],
        ["Loại thay đổi", " / ".join(pr.KIND_LABELS.values())],
        ["Trước / Sau", "Tên sản phẩm; dòng đầu mô tả; tên hoặc link ảnh bìa; "
         "bảng phân loại (mỗi dòng: tên | giá | SKU | tồn; thêm dòng 'ẩn: mã1, mã2'); "
         "tồn kho khi đưa sản phẩm trở lại."],
        ["Cửa sổ đo (ngày)", f"Từ {pr.MIN_WINDOW_DAYS} ngày trở lên."],
        ["Phụ thuộc (ref)", "Mã của thay đổi phải chạy trước, cách nhau bằng dấu phẩy."],
        ["Quyết định của shop",
         "đồng ý / không đồng ý / đề xuất chỉnh sửa (để trống = chưa quyết định)."],
        ["Trạng thái", "chưa / đang / hoàn thành. 'hoàn thành' cần Ngày thực hiện và đã đồng ý; "
         "thay đổi được ghi vào đúng ngày đó."],
        ["Tên sản phẩm", f"Tối đa {config.MAX_TITLE_CHARS} ký tự."],
    ]  # fmt: skip
    return xlsx_io.write_workbook(
        [
            xlsx_io.SheetSpec(
                pr.SHEET,
                [[(h, xlsx_io.STYLE_HEADER) for h in head], *sample],
                widths=[10, 16, 24, 36, 36, 32, 14, 16, 16, 16, 20, 14],
            ),
            xlsx_io.SheetSpec(
                "Hướng dẫn",
                [[(c, xlsx_io.STYLE_HEADER) for c in notes[0]], *notes[1:]],
                widths=[24, 100],
            ),
        ]
    )


# ------------------------------------------------------------------------------ reading


def _read(data: bytes) -> list[list[str | None]]:
    try:
        sheets = xlsx_io.read_workbook(data)
    except xlsx_io.WorkbookUnreadable as exc:
        raise ImportFileError(str(exc)) from None
    if pr.SHEET in sheets:
        return sheets[pr.SHEET]
    first = next(iter(sheets.values()), None)
    if first is None:
        raise ImportFileError("the workbook has no sheet")
    return first


def _naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


async def _context(
    session: AsyncSession, shop_id: uuid.UUID, env: RecoEnv, today: date
) -> pr.Context:
    items = {i: env.name(i) for i in {*env.ctx.catalog.items, *env.listing_item_ids()}}
    titles = {i: li.title for i, li in env.listings.items() if li.title}
    refs = (
        await session.execute(
            select(
                PlannedChangeRef.external_ref, PlannedChangeRef.content_hash, PlannedChangeRef.state
            ).where(PlannedChangeRef.shop_id == shop_id)
        )
    ).all()
    executed = (
        await session.execute(
            select(ShopProposal.item_id, ShopProposalExecution.executed_at)
            .join(ShopProposal, ShopProposal.id == ShopProposalExecution.proposal_id)
            .where(ShopProposalExecution.shop_id == shop_id, ShopProposal.item_id.is_not(None))
        )
    ).all()
    days: dict[str, list[date]] = {}
    for item, at in executed:
        days.setdefault(str(item), []).append(at.date())
    return pr.Context(
        today=today,
        known_items=items,
        current_titles=titles,
        banned_terms=env.banned_terms,
        existing={ref: (h, state or {}) for ref, h, state in refs},
        executed_days=days,
    )


# ------------------------------------------------------------------------------ card


def _ensure_listing(env: RecoEnv, item: str) -> lst.Listing:
    li = env.listings.get(item)
    if li is None:
        li = lst.Listing(item_id=item, title=env.name(item))
        env.listings[item] = li
    return li


def candidate_of(env: RecoEnv, row: pr.PlannedRow, depends: list[str]) -> Candidate:
    assert row.kind is not None
    li = _ensure_listing(env, row.item_id)
    inputs = dict(row.inputs)
    extra: dict[str, Any] = {}
    kind = row.kind
    if kind == "title":
        extra = {
            "current_title": li.title or env.name(row.item_id),
            "core": [k.keyword for k in li.core()],
            "notes": [],
        }
    elif kind == "description_first_line":
        extra = {"current_first_line": row.before_text.split("\n", 1)[0] or None}
    elif kind == "cover_image":
        extra = {
            "cover_url": li.cover_url,
            "before_text": row.before_text or "Ảnh bìa hiện tại",
            "after_text": f"Ảnh bìa mới: {row.inputs.get('image_ref', '')}",
            "image_ref": row.inputs.get("image_ref"),
        }
        inputs = {}
    elif kind == "variation_restructure":
        parsed = pr.parse_variations(row.before_text) if row.before_text else None
        extra = {"current_variations": (parsed or {}).get("variations", [])}
    elif kind == "listing_relist":
        extra = {"current_stock": env.stock(row.item_id)}
    if depends:
        inputs["depends_on"] = list(depends)
    return Candidate(kind=kind, items=(row.item_id,), inputs=inputs, extra=extra, reason=row.reason)


def _download_of(row: pr.PlannedRow) -> dict[str, Any] | None:
    ref = str(row.inputs.get("image_ref") or "")
    if row.kind != "cover_image" or not ref:
        return None
    url = ref if ref.lower().startswith("https://") else None
    return {"label": "Tải ảnh bìa mới", "ref": ref, "url": url}


def build_row_card(
    env: RecoEnv,
    row: pr.PlannedRow,
    *,
    now: datetime,
    depends: list[dict[str, Any]] | None = None,
    import_number: int | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """``(card, None)`` or ``(None, refusal text)``."""
    cand = candidate_of(
        env, row, [d["ref"] for d in depends or [{"ref": r} for r in row.depends_on]]
    )
    ev = evaluate(env, cand)
    if ev.refusal:
        return None, manual.refusal(ev.refusal)["message"]
    card = build_card(env, cand, now=now)
    if card is None:
        return None, manual.refusal("no_order_lines")["message"]
    card["execution_sheet"]["dependencies"] = [
        {
            "ref": d["ref"],
            "code": d.get("code"),
            "text": f"Chỉ làm sau khi {d['ref']} đã chạy xong.",
        }
        for d in depends or [{"ref": r} for r in row.depends_on]
    ]
    download = _download_of(row)
    if download is not None:
        card["execution_sheet"]["downloads"] = [download]
    if row.window_days:
        plan = card["measurement_plan"]
        plan["planned_days"] = row.window_days
        plan["label"] = f"Kết quả sau {row.window_days} ngày"
        plan["source"] = "import"
        plan["pooled_only"] = False
    card["external_ref"] = row.ref
    card["planned"] = {
        "ref": row.ref,
        "reason": row.reason,
        "cost": row.cost,
        "window_days": row.window_days,
        "planned_on": row.on.isoformat() if row.on else None,
        "depends_on": depends or [{"ref": r, "code": None} for r in row.depends_on],
        "decision": row.decision,
        "decision_label": pr.DECISION_LABELS[row.decision],
        "status": row.status,
        "status_label": pr.STATUS_LABELS[row.status],
        "import_number": import_number,
        "estimated": spec(row.kind or "title").target_metric != "none",
    }
    return card, None


def _brief(card: dict[str, Any] | None) -> dict[str, Any] | None:
    if card is None:
        return None
    pm = card["predicted"]["money_per_month"]["total"]
    estimated = card["planned"]["estimated"] and pm["p50"]["dprofit"] is not None
    return {
        "title": card["title"],
        "change_kind": card["change_kind"],
        "estimated": bool(estimated),
        "dprofit_p10": pm["p10"]["dprofit"] if estimated else None,
        "dprofit_p50": pm["p50"]["dprofit"] if estimated else None,
        "dprofit_p90": pm["p90"]["dprofit"] if estimated else None,
        "note": None if estimated else "không ước tính",
        "page": card["execution_sheet"]["page"],
        "steps": card["execution_sheet"]["steps"],
    }


# ------------------------------------------------------------------------------ preview


async def _prepare(
    session: AsyncSession, shop_id: uuid.UUID, data: bytes, *, now: datetime
) -> tuple[Preview, RecoEnv | None]:
    if len(data) > MAX_FILE_BYTES:
        raise ImportFileError("file too large")
    file_hash = hashlib.sha256(data).hexdigest()
    cells = _read(data)
    today = now.date()
    parsed, missing = pr.parse_sheet(cells, today)
    if missing:
        return Preview(file_hash, [], [], missing), None
    env = await load_env(session, shop_id, now=now)
    if env is None:
        raise ProposalError(ERROR_NO_DATA, 409, "shop has no Shopee numbers")
    ctx = await _context(session, shop_id, env, today)
    checked = pr.check_rows(parsed, ctx)
    plans: list[RowPlan] = []
    refs = {ref: card_id for ref, card_id in await _ref_cards(session, shop_id)}
    for row in checked.rows:
        problems = list(checked.rejected.get(row.row, []))
        warns = [w for w in checked.warnings if w.row == row.row]
        action = "rejected"
        card = None
        prior = ctx.existing.get(row.ref)
        if not problems:
            if prior is not None:
                move = pr.state_move(prior[1], row.state())
                action = "unchanged" if move == "same" else "advance"
            else:
                card, why = build_row_card(env, row, now=now)
                if card is None:
                    problems.append(pr.Problem(row.row, row.ref, "cannot_build", "Sau", why or ""))
                else:
                    action = "create"
        plans.append(RowPlan(row, action, problems, warns, card, refs.get(row.ref)))
    return Preview(file_hash, plans, checked.order), env


async def _ref_cards(session: AsyncSession, shop_id: uuid.UUID) -> list[tuple[str, uuid.UUID]]:
    found = await session.execute(
        select(PlannedChangeRef.external_ref, PlannedChangeRef.card_id).where(
            PlannedChangeRef.shop_id == shop_id
        )
    )
    return [(r, c) for r, c in found.all()]


async def preview_import(
    session: AsyncSession, shop_id: uuid.UUID, data: bytes, *, now: datetime
) -> Preview:
    preview, _ = await _prepare(session, shop_id, data, now=_naive(now))
    return preview


# ------------------------------------------------------------------------------- apply


def clean_reason(reason: str) -> str:
    text = " ".join((reason or "").split())
    if not text or len(text) > MAX_REASON_CHARS:
        raise ProposalError(ERROR_REASON, 422, "a reason of 1 to 500 characters is required")
    return text


def _when(on: date) -> datetime:
    return datetime.combine(on, time.min)


async def _decide(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    card: dict[str, Any],
    row: pr.PlannedRow,
    actor: Actor,
    *,
    number: int,
    now: datetime,
    decided_at: datetime,
) -> None:
    """Record the shop's decision on a sent card (the importer writes it down)."""
    p = await session.get(ShopProposal, card_id)
    assert p is not None
    seller = actor.kind == "seller"
    status = {
        "approve": STATUS_APPROVED,
        "reject": STATUS_REJECTED,
        "change": STATUS_CHANGES_REQUESTED,
    }[row.decision or "approve"]
    approval = await proposals.record_approval(
        session,
        p,
        decision=status,
        channel="in_app" if seller else "document",
        decided_at=decided_at,
        now=now,
        decided_by_user_id=actor.user_id if seller else None,
        recorded_by_staff_id=None if seller else actor.staff_id,
        evidence_ref=None if seller else f"planned-changes:{number}:{row.ref}",
        note=f"import {row.ref}",
        snapshot_extra={"code": p.code, "external_ref": row.ref, "chosen_version": 1},
    )
    subject = ("item", row.item_id)
    common = {
        "family": card["family"],
        "change_kind": card["change_kind"],
        "subject": subject,
        "code": p.code,
    }
    if row.decision == "approve":
        await store.write_event(
            session,
            shop_id,
            card_id,
            event_type=EVENT_ACCEPTED,
            actor=ACTOR_SELLER,
            occurred_at=decided_at,
            dedup_key=keys.accepted(approval.id),
            payload={
                "approval_id": str(approval.id),
                "chosen_version": 1,
                "imported": True,
                "external_ref": row.ref,
                "approved_with": {
                    "inputs": card["inputs"],
                    "execution_sheet": card["execution_sheet"],
                },
            },
            **common,
        )
    elif row.decision == "reject":
        await store.write_event(
            session,
            shop_id,
            card_id,
            event_type=EVENT_DISMISSED,
            actor=ACTOR_SELLER,
            occurred_at=decided_at,
            dedup_key=keys.dismissed(card_id),
            payload={"approval_id": str(approval.id), "imported": True},
            reason_code="unspecified",
            **common,
        )
    else:
        await store.write_event(
            session,
            shop_id,
            card_id,
            event_type=EVENT_EDITED,
            actor=ACTOR_SELLER,
            occurred_at=decided_at,
            dedup_key=f"edited:{approval.id}",
            payload={"request": row.reason, "approval_id": str(approval.id), "imported": True},
            **common,
        )


async def _execute(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    row: pr.PlannedRow,
    actor: Actor,
    *,
    number: int,
    now: datetime,
) -> None:
    assert row.on is not None
    await reco_service.mark_executed(
        session,
        shop_id,
        card_id,
        now=now,
        executed_at=_when(row.on),
        user_id=actor.user_id if actor.kind == "seller" else None,
        staff_id=actor.staff_id,
        evidence_ref=f"planned-changes:{number}:{row.ref}",
        payload_extra={"imported": True, "readback": False, "external_ref": row.ref},
    )


async def _next_number(session: AsyncSession, shop_id: uuid.UUID) -> int:
    last = await session.scalar(
        select(func.max(PlannedChangeImport.number)).where(PlannedChangeImport.shop_id == shop_id)
    )
    return int(last or 0) + 1


async def apply_import(
    session: AsyncSession,
    shop_id: uuid.UUID,
    data: bytes,
    *,
    actor: Actor,
    reason: str,
    expected_hash: str | None = None,
    now: datetime,
) -> ApplyResult:
    """Write the valid rows; never commits (the route does). Rejected rows write nothing."""
    now = _naive(now)
    reason = clean_reason(reason)
    preview, env = await _prepare(session, shop_id, data, now=now)
    if expected_hash is not None and expected_hash != preview.file_hash:
        raise FileMismatch("the file is not the one that was checked")
    if preview.missing_columns or env is None:
        raise ImportFileError("missing columns: " + ", ".join(preview.missing_columns))
    todo = [p for p in preview.plans if p.action in ("create", "advance")]
    if not todo:
        raise NothingToApply("the file holds no new or changed row")
    number = await _next_number(session, shop_id)
    record = PlannedChangeImport(
        id=uuid.uuid4(),
        shop_id=shop_id,
        number=number,
        file_hash=preview.file_hash,
        reason=reason,
        set_by=actor.set_by,
        set_by_user_id=actor.user_id,
        set_by_staff_id=actor.staff_id,
        summary={},
        created_at=now,
    )
    session.add(record)
    await session.flush()
    by_ref = {p.row.ref: p for p in preview.plans}
    code_of: dict[str, str | None] = {}
    for ref, card_id in await _ref_cards(session, shop_id):
        proposal = await session.get(ShopProposal, card_id)
        code_of[ref] = proposal.code if proposal else None
    out: list[dict[str, Any]] = []
    executed = 0
    for ref in [*preview.order, *[p.row.ref for p in todo if p.row.ref not in preview.order]]:
        plan = by_ref[ref]
        if plan.action not in ("create", "advance"):
            continue
        row = plan.row
        if plan.action == "create":
            depends = [{"ref": d, "code": code_of.get(d)} for d in row.depends_on]
            card, why = build_row_card(env, row, now=now, depends=depends, import_number=number)
            if card is None:
                raise ProposalError(ERROR_FILE, 422, f"{ref}: {why}")
            created = await manual.create_manual(
                session,
                shop_id,
                [
                    {
                        "label": row.ref,
                        "change_kind": row.kind,
                        "items": [row.item_id],
                        "extra": {},
                        "inputs": card["inputs"],
                    }
                ],
                0,
                False,
                actor.manual(),
                now=now,
                env=env,
                cards=[card],
                origin=ORIGIN_IMPORT,
            )
            card_id = uuid.UUID(created["id"])
            code_of[ref] = created["card"]["code"]
            await store.set_meta(session, shop_id, card_id, {"external_ref": ref})
            session.add(
                PlannedChangeRef(
                    id=uuid.uuid4(),
                    shop_id=shop_id,
                    external_ref=ref,
                    card_id=card_id,
                    import_id=record.id,
                    content_hash=row.content_hash(),
                    state={},
                    updated_at=now,
                )
            )
            await session.flush()
            proposal = await session.get(ShopProposal, card_id)
            assert proposal is not None
            if row.on is not None:
                proposal.planned_start = row.on
            prior_state: dict[str, Any] = {}
        else:
            assert plan.prior_card_id is not None
            card_id = plan.prior_card_id
            proposal = await session.get(ShopProposal, card_id)
            assert proposal is not None
            card = await store.card_payload(session, shop_id, card_id) or {}
            prior_state = dict(
                (
                    await session.scalar(
                        select(PlannedChangeRef.state).where(
                            PlannedChangeRef.shop_id == shop_id,
                            PlannedChangeRef.external_ref == ref,
                        )
                    )
                )
                or {}
            )
        if proposal.status == STATUS_DRAFT:
            await proposals.send(session, proposal, now=now)
        did = "created" if plan.action == "create" else "advanced"
        if row.decision and prior_state.get("decision") is None and proposal.status == "sent":
            decided = _when(row.on) if row.status == "done" and row.on else now
            await _decide(
                session, shop_id, card_id, card, row, actor, number=number, now=now,
                decided_at=min(decided, now),
            )  # fmt: skip
        ran = False
        if row.status == "done" and row.on is not None and proposal.status == STATUS_APPROVED:
            await _execute(session, shop_id, card_id, row, actor, number=number, now=now)
            executed += 1
            ran = True
        ref_row = await session.scalar(
            select(PlannedChangeRef).where(
                PlannedChangeRef.shop_id == shop_id, PlannedChangeRef.external_ref == ref
            )
        )
        assert ref_row is not None
        ref_row.state = row.state()
        ref_row.updated_at = now
        out.append(
            {
                "ref": ref,
                "item_id": row.item_id,
                "change_kind": row.kind,
                "card_id": str(card_id),
                "code": proposal.code,
                "action": did,
                "decision": row.decision,
                "status": row.status,
                "executed_on": row.on.isoformat() if ran and row.on else None,
            }
        )
    skipped = [
        {"ref": p.row.ref, "action": p.action, "problems": [x.kind for x in p.problems]}
        for p in preview.plans
        if p.action in ("unchanged", "rejected")
    ]
    counts = preview.counts()
    record.summary = {"counts": {**counts, "executed": executed}, "rows": out, "skipped": skipped}
    await reco_service.requeue(session, shop_id, now=now)
    await session.flush()
    return ApplyResult(
        number=number,
        file_hash=preview.file_hash,
        reason=reason,
        applied_at=now,
        created=counts["create"],
        advanced=counts["advance"],
        executed=executed,
        unchanged=counts["unchanged"],
        rejected=counts["rejected"],
        rows=out,
    )


# ------------------------------------------------------------------------------ versions


def import_json(r: PlannedChangeImport, *, detail: bool = False) -> dict[str, Any]:
    summary = r.summary or {}
    out: dict[str, Any] = {
        "number": r.number,
        "applied_at": r.created_at.isoformat(),
        "set_by": r.set_by,
        "reason": r.reason,
        "file_hash": r.file_hash,
        "counts": summary.get("counts", {}),
    }
    if detail:
        out["rows"] = summary.get("rows", [])
        out["skipped"] = summary.get("skipped", [])
    return out


async def list_imports(session: AsyncSession, shop_id: uuid.UUID) -> list[dict[str, Any]]:
    found = await session.scalars(
        select(PlannedChangeImport)
        .where(PlannedChangeImport.shop_id == shop_id)
        .order_by(PlannedChangeImport.number.desc())
    )
    return [import_json(r) for r in found]


async def get_import(
    session: AsyncSession, shop_id: uuid.UUID, number: int
) -> dict[str, Any] | None:
    found = await session.scalar(
        select(PlannedChangeImport).where(
            PlannedChangeImport.shop_id == shop_id, PlannedChangeImport.number == number
        )
    )
    return None if found is None else import_json(found, detail=True)
