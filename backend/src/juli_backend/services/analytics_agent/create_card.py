"""J10 "tạo thẻ": a free request becomes a typed slot set (the parser), code validates it against
Shopee's limits and the builder's own specs, asks ONE question for what is missing (with the shop's
own suggested values), and ends in a Juli DRAFT card. Never sent, never executed. Numbers come from
the seller's words or from the recommendation engine, never from a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from juli_backend.services.analytics_agent import fmt

#: the builder KIND_KEYS Juli may draft from chat (no ads / affiliate)
CARD_TYPES = (
    "voucher",
    "combo",
    "add_on",
    "gift",
    "product_discount",
    "price",
    "flash_sale",
    "variation_set",
    "title",
    "cover_image",
    "description_first_line",
    "price_display",
)
SLOT_KEYS = (
    "card_type",
    "from_date",
    "to_date",
    "start_hour",
    "product_phrase",
    "amount",
    "amount_unit",
    "min_spend",
    "quantity",
    "name",
)
#: required slots per card type (`product` = a resolved listing)
REQUIRED: dict[str, tuple[str, ...]] = {
    "voucher": ("from_date", "to_date", "amount", "min_spend"),
    "product_discount": ("name", "from_date", "to_date", "amount", "product"),
    "combo": ("name", "from_date", "to_date", "amount", "product"),
    "add_on": ("name", "from_date", "to_date", "product"),
    "gift": ("name", "from_date", "to_date", "product", "quantity"),
    "flash_sale": ("product", "from_date", "start_hour", "quantity"),
    "price": ("amount", "product"),
    "variation_set": ("product",),
    "title": ("product",),
    "cover_image": ("product",),
    "description_first_line": ("product",),
    "price_display": ("product",),
}
SLOT_VI = {
    "from_date": "ngày bắt đầu",
    "to_date": "ngày kết thúc",
    "amount": "mức giảm",
    "min_spend": "đơn tối thiểu",
    "name": "tên",
    "product": "sản phẩm",
    "quantity": "số lượng",
    "start_hour": "khung giờ",
}
FLASH_AHEAD_DAYS = 7
#: Flash Sale of the shop: the fixed khung giờ (start hour, end hour) captured from Seller Centre.
#: TODO: Track F owns this constant in `shopee_builder/specs.py`; use theirs at merge.
FLASH_SLOTS = ((0, 2), (2, 9), (9, 12), (12, 15), (15, 17), (17, 19), (19, 21), (21, 24))


def name_limit(card_type: str) -> int | None:
    """Shopee form name limits, read from the builder's own specs (never a second number)."""
    from juli_backend.services.shopee_builder import specs as sp

    if card_type == "voucher":
        meta = sp.VoucherSpec.model_fields["label"].metadata
        return next((m.max_length for m in meta if hasattr(m, "max_length")), None)
    return {
        "combo": sp.MAX_COMBO_NAME,
        "add_on": sp.MAX_COMBO_NAME,
        "gift": sp.MAX_COMBO_NAME,
        "product_discount": sp.MAX_PROGRAMME_NAME,
        "title": sp.MAX_TITLE_CHARS,
    }.get(card_type)


def max_days(card_type: str) -> int | None:
    from juli_backend.services.shopee_builder import specs as sp

    return {"voucher": sp.MAX_VOUCHER_DAYS, "product_discount": sp.MAX_DISCOUNT_DAYS}.get(card_type)


#: TODO: import VOUCHER_NAME, VOUCHER_MIN_PARTS, VOUCHER_SCOPE_LABELS, voucher_scope_label() from
#: `shopee_recommendations/kinds.py` after Track S merges; these strings match theirs exactly.
VOUCHER_NAME = "Mã Giảm Giá"
VOUCHER_SCOPE_VI = {"shop": "Voucher toàn Shop", "product": "Voucher sản phẩm"}
VOUCHER_MIN_VI = {True: "đơn tối thiểu", False: "không đơn tối thiểu"}


def voucher_label(product: bool, has_min: bool) -> str:
    scope = VOUCHER_SCOPE_VI["product" if product else "shop"]
    return f"{VOUCHER_NAME} · {scope} · {VOUCHER_MIN_VI[has_min]}"


@dataclass
class Slots:
    card_type: str | None = None
    from_date: date | None = None
    to_date: date | None = None
    start_hour: int | None = None
    product_phrase: str | None = None
    amount: float | None = None
    amount_unit: str | None = None  # vnd | pct
    min_spend: int | None = None
    quantity: int | None = None
    name: str | None = None
    item_id: str | None = None
    item_name: str | None = None
    problems: list[str] = field(default_factory=list)


def _date(v: Any) -> date | None:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def slots_of(intent: dict[str, Any]) -> Slots:
    ct = intent.get("card_type")
    return Slots(
        card_type=ct if ct in CARD_TYPES else None,
        from_date=_date(intent.get("from_date")),
        to_date=_date(intent.get("to_date")),
        start_hour=None if intent.get("start_hour") is None else int(intent["start_hour"]),
        product_phrase=(intent.get("product_phrase") or None),
        amount=None if intent.get("amount") is None else float(intent["amount"]),
        amount_unit=intent.get("amount_unit")
        if intent.get("amount_unit") in ("vnd", "pct")
        else None,
        min_spend=None if intent.get("min_spend") is None else int(intent["min_spend"]),
        quantity=None if intent.get("quantity") is None else int(intent["quantity"]),
        name=(intent.get("name") or None),
        item_id=intent.get("item_id"),
        item_name=intent.get("item_name"),
    )


def fill(intent: dict[str, Any], answer: str) -> dict[str, Any]:
    """Apply a tapped suggestion ("amount=20000;unit=vnd;min_spend=150000") to the intent."""
    out = dict(intent)
    for part in answer.split(";"):
        k, _, v = part.partition("=")
        if k == "unit":
            out["amount_unit"] = v
        elif k in ("amount", "min_spend", "quantity", "start_hour"):
            out[k] = float(v) if k == "amount" else int(float(v))
        elif k in ("from_date", "to_date", "name", "item_id", "item_name", "card_type"):
            out[k] = v
    return out


def missing(s: Slots) -> list[str]:
    need = REQUIRED.get(s.card_type or "", ())
    out = []
    for slot in need:
        if slot == "product":
            if not s.item_id:
                out.append("product")
        elif getattr(s, slot) is None:
            out.append(slot)
    return out


def validate(s: Slots, today: date) -> list[str]:
    """Shopee's limits; Vietnamese problems, [] = fine."""
    p: list[str] = []
    ct = s.card_type or ""
    if s.from_date and s.from_date < today:
        p.append("Ngày bắt đầu không được ở quá khứ.")
    if s.from_date and s.to_date and s.to_date < s.from_date:
        p.append("Ngày kết thúc phải sau ngày bắt đầu.")
    limit = max_days(ct)
    if limit and s.from_date and s.to_date and (s.to_date - s.from_date).days + 1 > limit:
        p.append(f"Thời gian chạy tối đa {limit} ngày.")
    lim = name_limit(ct)
    if lim and s.name and len(s.name) > lim:
        p.append(f"Tên tối đa {lim} ký tự (đang {len(s.name)}).")
    if s.amount is not None and s.amount_unit == "pct" and not 0 < s.amount <= 90:
        p.append("Mức giảm phần trăm phải lớn hơn 0 và tối đa 90%.")
    if s.amount is not None and s.amount_unit == "vnd" and s.min_spend and s.amount >= s.min_spend:
        p.append("Mức giảm phải nhỏ hơn đơn tối thiểu.")
    if ct == "flash_sale" and s.start_hour is not None:
        if s.start_hour not in {a for a, _ in FLASH_SLOTS}:
            p.append("Khung giờ Flash Sale phải là một trong: " + slots_vi() + ".")
    if ct == "flash_sale" and s.from_date:
        if not today < s.from_date <= today + timedelta(days=FLASH_AHEAD_DAYS):
            p.append(
                f"Flash Sale chỉ đăng ký trước tối đa {FLASH_AHEAD_DAYS} ngày, "
                "theo khung giờ cố định."
            )
    return p


def slots_vi() -> str:
    return ", ".join(f"{a:02d}–{b:02d}h" for a, b in FLASH_SLOTS)


def window_vi(s: Slots) -> str | None:
    if not (s.from_date and s.to_date):
        return None
    return f"{s.from_date:%d/%m} 00:00–{s.to_date:%d/%m} 23:59"


def money(v: float, unit: str | None) -> str:
    return f"{v:g}%".replace(".", ",") if unit == "pct" else fmt.value("gmv", v)


def question(miss: list[str], problems: list[str]) -> str:
    head = "Còn thiếu: " + ", ".join(SLOT_VI[m] for m in miss) + "." if miss else ""
    return " ".join([*problems, head]).strip()


def suggestions(
    s: Slots, miss: list[str], engine_inputs: dict[str, Any] | None
) -> list[dict[str, str]]:
    """Options from the shop's own estimate (the engine's proposal for the kind); [] when Juli has
    none."""
    out: list[dict[str, str]] = []
    if s.card_type == "voucher" and engine_inputs and ("amount" in miss or "min_spend" in miss):
        ms = int(engine_inputs.get("min_spend") or 0)
        if engine_inputs.get("pct") is not None:
            v, unit = float(engine_inputs["pct"]), "pct"
        elif engine_inputs.get("value") is not None:
            v, unit = float(engine_inputs["value"]), "vnd"
        else:
            return out
        out.append(
            {
                "label_vi": f"Giảm {money(v, unit)} · đơn tối thiểu "
                f"{fmt.value('gmv', ms)} (Juli gợi ý)"
                if ms
                else f"Giảm {money(v, unit)} · không đơn tối thiểu (Juli gợi ý)",
                "value": f"amount={v:g};unit={unit};min_spend={ms}",
            }
        )
    if "start_hour" in miss:
        out += [
            {"label_vi": f"{a:02d}:00–{b:02d}:00", "value": f"start_hour={a}"}
            for a, b in FLASH_SLOTS
        ]
    if "min_spend" in miss and "amount" not in miss:
        out.append({"label_vi": "Không đơn tối thiểu", "value": "min_spend=0"})
    return out


def voucher_spec(s: Slots) -> dict[str, Any]:
    """The builder's `VoucherSpec` shape (read-only use of `shopee_builder.specs`)."""
    spec: dict[str, Any] = {
        "kind": "voucher",
        "scope": "product" if s.item_id else "shop",
        "item_ids": [s.item_id] if s.item_id else [],
        "discount_type": "pct" if s.amount_unit == "pct" else "amount",
        "value": s.amount,
        "min_spend": s.min_spend or 0,
        "start": s.from_date.isoformat() if s.from_date else None,
        "end": s.to_date.isoformat() if s.to_date else None,
    }
    if s.name:
        spec["label"] = s.name
    return spec


def product_discount_spec(s: Slots) -> dict[str, Any]:
    return {
        "kind": "product_discount",
        "name": s.name,
        "item_id": s.item_id,
        "discount_pct": s.amount,
        "start": s.from_date.isoformat() if s.from_date else None,
        "end": s.to_date.isoformat() if s.to_date else None,
    }


def check_spec(spec: dict[str, Any]) -> str | None:
    """Run the real pydantic model; the first refusal in Vietnamese-neutral English, or None."""
    from pydantic import TypeAdapter, ValidationError

    from juli_backend.services.shopee_builder import specs as sp

    try:
        TypeAdapter(sp.VersionSpec).validate_python(spec)
    except ValidationError as exc:
        return str(exc.errors()[0]["msg"])
    return None


#: builder kind -> the engine's generator kind (drafts that Juli proposes values for itself)
ENGINE_KIND = {
    "combo": "bundle_deal",
    "add_on": "add_on",
    "gift": "gift",
    "flash_sale": "flash_sale",
    "price": "price",
    "variation_set": "variation_set",
    "title": "title",
    "cover_image": "cover_image",
    "price_display": "price_display",
}


def _pending(intent: dict[str, Any], restated: str, as_of: date) -> dict[str, Any]:
    return {
        "intent": intent,
        "dec": {"mode": "create"},
        "remaining": [["chain", []]],
        "turns": 0,
        "restated": restated,
        "anchor": as_of.isoformat(),
    }


async def run_create(
    *,
    intent: dict[str, Any],
    data: Any,
    engine: Any,
    jev: Any,
    labels: Any,
    as_of: date,
    restated: str,
    emit: Any,
    out_cards: Any,
) -> str:
    """Emit the events of one "tạo thẻ" request. Returns asked | problem | drafted | duplicate |
    refused. `out_cards` is the `CardOutcome` the draft is appended to."""
    from juli_backend.services.analytics_agent import cards as cardstage
    from juli_backend.services.analytics_agent import routing
    from juli_backend.services.analytics_agent.weekly import _same_change

    today = as_of + timedelta(days=1)
    s = slots_of(intent)

    async def ask(item_vi: str, options: list[dict[str, str]], it: dict[str, Any]) -> str:
        await emit(
            {
                "type": "needs_choice",
                "item": "chain",  # the contract's open item kind; the pending marks `create`
                "question_vi": item_vi,
                "options": options,
                "pending": _pending(it, restated, as_of),
            }
        )
        return "asked"

    if s.card_type is None:
        return await ask(
            "Bạn muốn tạo loại thẻ nào?",
            [
                {
                    "label_vi": labels.kind(
                        ENGINE_KIND.get(c, "min_spend_voucher" if c == "voucher" else c)
                    ),
                    "value": f"card_type={c}",
                }
                for c in CARD_TYPES
            ],
            intent,
        )
    needs_product = "product" in REQUIRED[s.card_type] or bool(s.product_phrase)
    if needs_product and not s.item_id and s.product_phrase:
        prod, _ = await routing.resolve_product(data, jev, intent)
        if prod["status"] == "found":
            intent = {**intent, "item_id": prod["item_id"], "item_name": prod["name"]}
            s = slots_of(intent)
        else:
            opts = [
                {
                    "label_vi": o["name"] or o["item_id"],
                    "value": f"item_id={o['item_id']};item_name={o['name'] or ''}",
                }
                for o in prod.get("options", [])
            ]
            return await ask("Bạn muốn nói sản phẩm nào?", opts, intent)
    problems = validate(s, today)
    if problems:
        await emit(
            {
                "type": "text_delta",
                "text": " ".join(problems) + " Bạn gửi lại yêu cầu giúp Juli nhé.",
            }
        )
        return "problem"
    miss = missing(s)
    if miss:
        inputs = None
        if (
            s.card_type == "voucher"
            and engine is not None
            and ("amount" in miss or "min_spend" in miss)
        ):
            eng = await engine.engine_card("min_spend_voucher", None, as_of)
            inputs = ((eng.get("card") or {}).get("inputs") if eng.get("ok") else None) or None
        return await ask(question(miss, problems), suggestions(s, miss, inputs), intent)
    if engine is None:
        await emit({"type": "no_card", "reason_vi": "Juli chưa tạo được thẻ nháp ở đây."})
        return "refused"
    ctype = s.card_type or ""
    kind = ENGINE_KIND.get(ctype, "min_spend_voucher" if ctype == "voucher" else ctype)
    if s.card_type in ("voucher", "product_discount"):
        spec = voucher_spec(s) if s.card_type == "voucher" else product_discount_spec(s)
        refusal = check_spec(spec)
        if refusal:
            await emit({"type": "text_delta", "text": f"Juli chưa tạo được thẻ này: {refusal}."})
            return "refused"
        built = await engine.build_custom(spec, as_of)
    else:
        built = await engine.engine_card(kind, s.item_id, as_of)
    if not built.get("ok"):
        await emit(
            {"type": "no_card", "reason_vi": "Juli chưa tạo được phương án cho yêu cầu này."}
        )
        return "refused"
    card = built["card"]
    custom = s.card_type in ("voucher", "product_discount")  # the seller's own numbers
    if not custom and not cardstage.estimable(card, kind):
        await emit(
            {
                "type": "no_card",
                "reason_vi": "Juli chưa ước tính được loại thẻ này nên chưa tạo thẻ nháp.",
            }
        )
        return "refused"
    for c in await data.open_cards():
        if _same_change(c, kind, s.item_id, card.get("title")) == "same":
            await emit(
                {
                    "type": "no_card",
                    "reason_vi": f"Đã có thẻ {c.get('code') or ''}".strip(),
                    "existing_card_code": c.get("code"),
                }
            )
            return "duplicate"
    ev = await cardstage.draft_event(out_cards, data, jev, labels, kind, s.item_id, card)
    if s.card_type == "voucher":
        ev["kind_vi"] = voucher_label(bool(s.item_id), (s.min_spend or 0) > 0)
    if w := window_vi(s):
        ev["window_vi"] = w
    await emit(ev)
    return "drafted"
