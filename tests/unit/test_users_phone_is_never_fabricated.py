"""First sighting writes no phone, and nothing invents one afterwards (#1972).

`users.phone` was `NOT NULL UNIQUE` because the column was the identity field
of a phone/OTP login that predates Google sign-in. When Google sign-in was
layered on (#1906), first-sighting provisioning had nothing to put there and
satisfied the constraint by deriving a number from the caller's own UUID::

    placeholder_phone = f"+849{user_id.int % 10_000_000_000:010d}"

Every Google-signed-in seller therefore carried a well-formed `+849` number
that was not theirs, that nothing in the column marked as synthetic, and that
occupied a UNIQUE slot a real number could later collide with -- while the
landing page offers 1:1 support to five trial shops, so the first human to work
from that column would have been messaging strangers.

Three separate properties have to hold for that to stay fixed, and each fails
independently, so each gets its own test here:

1. **Provisioning writes no phone.** The behavioural check, through the real
   `get_for_authentication` entry point against a real session.
2. **No source derives a phone from a user id.** A returning caller could
   re-introduce the same expression in a different file --
   `services/tiktok/business_account_holder_store.py` had an independent copy
   of it -- and test 1 would still pass.
3. **No reader treats `users.phone` as a contact channel.** The column is now
   nullable, so a reader that assumed a value is a `None` away from a crash
   or, worse, from "contact" silently meaning nothing at all.

SQLITE, NOT POSTGRES. The `session` fixture is SQLite in-memory
(`tests/unit/conftest.py::engine`). Everything asserted below about row
contents holds on either engine, but nothing here proves the *Postgres* UNIQUE
behaviour for NULLs -- see `test_users_phone_nullable_migration.py`, which is
Postgres-gated, for that.
"""

from __future__ import annotations

import ast
import re
import uuid
from pathlib import Path

from juli_backend.models.models import User
from juli_backend.repositories import UsersRepo

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend/src/juli_backend"


def _backend_sources() -> list[Path]:
    return sorted(p for p in BACKEND.rglob("*.py") if "migrations" not in p.parts)


def _relative(path: Path) -> str:
    return str(path.relative_to(BACKEND))


# WHY AST AND NOT GREP. Every file below is *documented* with the expression it
# must no longer execute -- that is the point of the comments #1972 left behind,
# and a regex over the raw text cannot tell the warning from the offence. The
# node shapes here exist only in code: a docstring quoting
# `f"+849{user_id.int % 10_000_000_000:010d}"` parses to one plain string
# constant, never to a JoinedStr with a FormattedValue inside it.


def _is_uuid_int(node: ast.AST) -> bool:
    """`<something>.int` -- the attribute that turns a UUID into a number."""
    return isinstance(node, ast.Attribute) and node.attr == "int"


def _interpolates_a_uuid_int(node: ast.JoinedStr) -> bool:
    return any(
        isinstance(part, ast.FormattedValue)
        and any(_is_uuid_int(inner) for inner in ast.walk(part.value))
        for part in node.values
    )


_PHONE_PREFIX = re.compile(r"\+\d{1,4}$")


def _looks_like_a_phone_template(node: ast.JoinedStr) -> bool:
    """An f-string whose literal head is a `+<country code>` dialling prefix."""
    return any(
        isinstance(part, ast.Constant)
        and isinstance(part.value, str)
        and _PHONE_PREFIX.search(part.value.strip())
        for part in node.values
    )


def _fabricated_phone_expressions(tree: ast.AST) -> list[str]:
    return [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        and _looks_like_a_phone_template(node)
        and _interpolates_a_uuid_int(node)
    ]


def _uuid_int_modulo_expressions(tree: ast.AST) -> list[str]:
    return [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and _is_uuid_int(node.left)
    ]


# ---------------------------------------------------------------------------
# 1. Provisioning writes no phone
# ---------------------------------------------------------------------------


async def test_first_sighting_provisioning_writes_no_phone(session) -> None:
    """The acceptance criterion of #1972, through the real entry point.

    `get_for_authentication` is what `core/security/dependencies.py` calls with
    the `sub` of a verified JWT; for a first-time Google sign-in there is no
    row, and this is the call that creates one.
    """
    user_id = uuid.uuid4()

    user = await UsersRepo(session).get_for_authentication(user_id)

    assert user.id == user_id
    assert user.phone is None, (
        f"first-sighting provisioning wrote phone={user.phone!r}. A number this "
        "seller never gave us is indistinguishable from one they did."
    )


async def test_first_sighting_stores_no_phone_in_the_row_itself(session) -> None:
    """Not just the returned object -- the persisted row."""
    user_id = uuid.uuid4()

    await UsersRepo(session).get_for_authentication(user_id)
    await session.flush()
    session.expire_all()

    persisted = await session.get(User, user_id)
    assert persisted is not None
    assert persisted.phone is None


async def test_first_sighting_is_idempotent_without_a_phone(session) -> None:
    """Re-authentication returns the same row rather than a second one.

    Idempotence used to be attributed to the deterministic placeholder. It was
    never the placeholder that provided it -- the primary key on `users.id`
    does -- and this test is what says so now that the placeholder is gone.
    """
    user_id = uuid.uuid4()
    repo = UsersRepo(session)

    first = await repo.get_for_authentication(user_id)
    second = await repo.get_for_authentication(user_id)

    assert first is second
    assert second.phone is None


async def test_two_phoneless_sellers_coexist(session) -> None:
    """Two first sightings both leave phone NULL and both survive.

    UNPROVEN HERE FOR POSTGRES. This runs on SQLite; that a UNIQUE index
    tolerates repeated NULLs is true of both engines but is only *proven* for
    Postgres by the Postgres-gated test in
    `test_users_phone_nullable_migration.py`.
    """
    repo = UsersRepo(session)
    first_id, second_id = uuid.uuid4(), uuid.uuid4()

    first = await repo.get_for_authentication(first_id)
    second = await repo.get_for_authentication(second_id)
    await session.flush()

    assert (first.phone, second.phone) == (None, None)
    assert first.id != second.id


# ---------------------------------------------------------------------------
# 2. No source derives a phone from a user id
# ---------------------------------------------------------------------------


def test_no_backend_source_derives_a_phone_number_from_a_user_id() -> None:
    """The fabrication is gone from every file, not just the one the issue named.

    `repositories/identity.py` was the call site #1972 reported, but
    `services/tiktok/business_account_holder_store.py` carried a verbatim copy
    of the same expression, so a fix confined to the reported line would have
    left an OAuth callback still minting the identical number.
    """
    offenders = {}
    for path in _backend_sources():
        found = _fabricated_phone_expressions(ast.parse(path.read_text(encoding="utf-8")))
        if found:
            offenders[_relative(path)] = found

    assert offenders == {}, (
        f"these files build a phone number out of a user id: {offenders}. A "
        "number derived from an identifier is still a number that may belong "
        "to a real person; `users.phone` is nullable (migration 064) so the "
        "honest value is NULL."
    )


def test_no_backend_source_takes_a_uuid_modulo() -> None:
    """The looser net: `<uuid>.int % <n>` anywhere, in or out of an f-string.

    Kept separate from the test above because the two fail for different
    reasons -- this one catches a fabrication that has been refactored out of
    the f-string into a local variable, which the phone-template shape no
    longer recognises.
    """
    offenders = {}
    for path in _backend_sources():
        found = _uuid_int_modulo_expressions(ast.parse(path.read_text(encoding="utf-8")))
        if found:
            offenders[_relative(path)] = found

    assert offenders == {}, (
        f"{offenders} reduce a UUID to a decimal integer. In this codebase that "
        "has had exactly one purpose -- manufacturing a phone number for the "
        "old NOT NULL constraint (#1972)."
    )


# ---------------------------------------------------------------------------
# 3. No unguarded reader
# ---------------------------------------------------------------------------

#: Every backend file that mentions `phone` at all, and why it is not a
#: contact-channel read of `users.phone`. The assertion below is on the SET:
#: a new file that touches `phone` fails until it is named here on purpose,
#: which is the only way this check keeps meaning anything as the tree grows.
ALLOWED_PHONE_MENTIONS = {
    # Writes, not reads. Both pass a fixed sentinel for an internal, non-seller
    # account (TikTok app review / advertiser), never a per-seller number.
    "services/tiktok/app_review_store.py",
    "services/tiktok/advertiser_oauth_store.py",
    "services/tiktok/oauth.py",
    # Write. Now passes no phone at all (#1972) -- only the comment mentions it.
    "services/tiktok/business_account_holder_store.py",
    # Write. Seeded demo tenants carry a visibly non-dialable marker string.
    "services/seeds/demo_tenant.py",
    "services/seeds/demo_cohort.py",
    # The definition of the column and of the write path.
    "models/models.py",
    "repositories/identity.py",
    # #1973's claim reader. Mentions `phone` only to explain that the verified
    # email is what replaces the fabricated one; it reads no `phone` claim and
    # writes no phone.
    "core/security/claims.py",
    # Redaction: these name `phone` in order to REMOVE it from logs and from
    # vendor payloads. They read nothing from `users`.
    "core/observability/logging.py",
    "services/tiktok/webhook_redaction.py",
    "services/analytics_kpi_masking/mask.py",
}


def test_users_phone_has_no_unguarded_contact_reader() -> None:
    """Nothing reads `users.phone` as a way to reach a seller.

    #1972's last checklist item. The column is nullable from migration 064, so
    a reader that assumed a value is now wrong in one of two ways: it raises on
    `None`, or -- much worse -- it silently treats "no phone on file" as a
    contact attempt that goes nowhere.

    The finding this pins is worth stating plainly: as of this change there is
    NO such reader anywhere in the backend. `users.phone` is write-only. No API
    schema exposes it, no service dials, exports or matches on it, and the only
    non-write mentions in the tree are redaction lists whose job is to strip
    the word from logs.
    """
    mentions = {
        _relative(path)
        for path in _backend_sources()
        if re.search(r"\bphone\b", path.read_text(encoding="utf-8"))
    }

    unexpected = sorted(mentions - ALLOWED_PHONE_MENTIONS)
    assert unexpected == [], (
        f"{unexpected} mention `phone` and are not on the reviewed list. If one "
        "of them READS users.phone, it must handle NULL explicitly -- the "
        "column no longer promises a value (#1972). If it does not, add it to "
        "ALLOWED_PHONE_MENTIONS with the reason."
    )


def test_no_api_surface_exposes_users_phone() -> None:
    """The API never hands `users.phone` to a client.

    A serialized phone is how a fabricated number escapes the database and
    becomes something a human acts on. This is the check that would have caught
    the original bug reaching a CSV export or a profile endpoint.
    """
    api_like = [
        path
        for path in _backend_sources()
        if _relative(path).split("/", 1)[0] in {"api", "schemas"}
    ]
    assert api_like, "expected to find api/ or schemas/ modules to scan"

    offenders = sorted(
        _relative(path)
        for path in api_like
        if re.search(r"\bphone\b", path.read_text(encoding="utf-8"))
    )

    assert offenders == [], f"{offenders} put `phone` on the API surface"


# ---------------------------------------------------------------------------
# The column itself
# ---------------------------------------------------------------------------


def test_users_phone_column_is_nullable_and_still_unique() -> None:
    """The model agrees with migration 064: nullable, and UNIQUE is retained.

    Both halves matter. Nullable is the fix; keeping UNIQUE is what lets the
    column still reject two sellers claiming the same real number, once real
    numbers start arriving.
    """
    column = User.__table__.c.phone

    assert column.nullable is True
    assert column.unique is True
    assert column.type.length == 20


def test_user_can_be_constructed_without_a_phone() -> None:
    """Constructing a `User` with no phone is legal at the ORM layer."""
    user = User(id=uuid.uuid4())

    assert user.phone is None
