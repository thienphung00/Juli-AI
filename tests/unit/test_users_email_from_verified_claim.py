"""The verified Google email stops being thrown away (#1973, email half).

A Supabase access token minted from a Google sign-in carries `email`,
`email_verified` and the seller's name -- signed, and already checked against
the project's JWKS by `verify_supabase_jwt`. The backend read `sub` and
discarded the rest, so after sign-in Juli held a UUID, a fabricated phone
(#1972) and no way to reach a seller it had offered 1:1 support to.

Two layers, tested separately because they fail separately:

* `core/security/claims.py` decides *what the token proves* -- in particular
  that an unverified address proves nothing and must not be stored. Pure
  function, no database.
* `UsersRepo.get_for_authentication` decides *what is written* -- populate on
  first sighting, fill a hole on a returning seller, never overwrite.

SCOPE. This is the email half only. #1973's Zalo/phone capture is NOT
implemented here: it carries an unsettled owner decision ("skippable or
required?") and sits inside the onboarding cold-start read (ADR-103 d.9),
which is not built.

SQLITE, NOT POSTGRES. The `session` fixture is SQLite in-memory. Row contents
assert identically on either engine; the column's real shape on Postgres is
proven in `test_users_email_migration.py`.
"""

from __future__ import annotations

import uuid

import pytest

from juli_backend.core.security.claims import VerifiedIdentity, verified_identity
from juli_backend.models.models import User
from juli_backend.repositories import UsersRepo

SUB = "3f1d9e2a-0000-4000-8000-000000000001"
EMAIL = "seller@example.com"
NAME = "Nguyễn Văn A"


def _google_payload(**overrides) -> dict:
    """A Supabase access token payload for a Google identity, as issued.

    Shaped from the real thing: `email` promoted to the top level, the
    verification flag and the profile fields under `user_metadata`.
    """
    payload = {
        "sub": SUB,
        "aud": "authenticated",
        "role": "authenticated",
        "email": EMAIL,
        "app_metadata": {"provider": "google", "providers": ["google"]},
        "user_metadata": {
            "email": EMAIL,
            "email_verified": True,
            "full_name": NAME,
            "name": NAME,
            "provider_id": "104729371937",
        },
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# What the token proves
# ---------------------------------------------------------------------------


def test_a_verified_google_token_yields_the_email_and_the_name() -> None:
    identity = verified_identity(_google_payload())

    assert identity == VerifiedIdentity(email=EMAIL, display_name=NAME)


def test_an_unverified_email_is_not_taken() -> None:
    """The whole point of reading `email_verified` rather than just `email`.

    A provider can carry an address the user typed and nobody checked. Writing
    that into `users.email` would repeat #1972's mistake in a new column: a
    contactable-looking value nobody confirmed.
    """
    payload = _google_payload()
    payload["user_metadata"]["email_verified"] = False

    identity = verified_identity(payload)

    assert identity.email is None
    assert identity.display_name == NAME, (
        "the name is not a contact channel and is kept regardless -- greeting "
        "someone by the name they chose costs nothing"
    )


def test_a_missing_verification_flag_is_not_a_verification() -> None:
    """Absent means unverified, never 'probably fine'."""
    payload = _google_payload()
    del payload["user_metadata"]["email_verified"]

    assert verified_identity(payload).email is None


@pytest.mark.parametrize("flag", [True, "true", "True", " TRUE "])
def test_the_verification_flag_is_read_in_both_forms_supabase_emits(flag) -> None:
    """Supabase has emitted the boolean and the string; both are affirmative."""
    payload = _google_payload()
    payload["user_metadata"]["email_verified"] = flag

    assert verified_identity(payload).email == EMAIL


@pytest.mark.parametrize("flag", [False, "false", None, 0, "yes", ""])
def test_anything_that_is_not_an_affirmative_is_treated_as_unverified(flag) -> None:
    payload = _google_payload()
    payload["user_metadata"]["email_verified"] = flag

    assert verified_identity(payload).email is None


def test_a_top_level_verification_flag_wins_over_the_metadata_one() -> None:
    """Newer Supabase promotes the flag; the promoted one is authoritative."""
    payload = _google_payload(email_verified=False)

    assert verified_identity(payload).email is None


def test_an_empty_payload_yields_nothing_rather_than_raising() -> None:
    """Authentication must not 500 on a token that simply carries no profile.

    An email/password Supabase user, or a provider with no `user_metadata` at
    all, is a legitimate caller. The columns stay NULL and the request
    proceeds.
    """
    identity = verified_identity({"sub": SUB})

    assert identity == VerifiedIdentity(email=None, display_name=None)
    assert identity.is_empty


def test_a_name_falls_back_from_full_name_to_name() -> None:
    payload = _google_payload()
    del payload["user_metadata"]["full_name"]

    assert verified_identity(payload).display_name == NAME


def test_values_are_trimmed_to_the_columns_that_hold_them() -> None:
    """`users.email` is String(320) and `display_name` String(100).

    Truncating a long name keeps something real; letting it through would fail
    the INSERT inside the authentication path and 500 the seller's first
    request.
    """
    payload = _google_payload()
    payload["user_metadata"]["full_name"] = "N" * 400

    identity = verified_identity(payload)

    assert len(identity.display_name) == 100


def test_whitespace_only_claims_are_nothing() -> None:
    payload = _google_payload(email="   ")
    payload["user_metadata"]["email"] = "  "
    payload["user_metadata"]["full_name"] = "\t"
    payload["user_metadata"]["name"] = ""

    assert verified_identity(payload).is_empty


# ---------------------------------------------------------------------------
# What gets written
# ---------------------------------------------------------------------------


async def test_first_sighting_stores_the_verified_email_and_name(session) -> None:
    """The acceptance criterion: no screen, no friction, no invented data."""
    user_id = uuid.uuid4()

    user = await UsersRepo(session).get_for_authentication(user_id, email=EMAIL, display_name=NAME)

    assert (user.email, user.display_name) == (EMAIL, NAME)
    assert user.phone is None, "#1972: nothing is fabricated to fill a column"


async def test_first_sighting_without_a_verified_claim_leaves_the_columns_null(
    session,
) -> None:
    user = await UsersRepo(session).get_for_authentication(uuid.uuid4())

    assert (user.email, user.display_name, user.phone) == (None, None, None)


async def test_a_returning_seller_whose_row_predates_the_column_is_backfilled(
    session,
) -> None:
    """THE BACKFILL (#1973), and the only one available.

    Supabase's `auth.users` lives in Supabase's project, not in Juli's
    Postgres, so no SQL migration has a claim to recover. The authority on a
    seller's verified address is a token that seller presents -- so the
    backfill happens on their next authenticated request, from the same signed
    claim a new row is built from.
    """
    user_id = uuid.uuid4()
    session.add(User(id=user_id, phone="+84901234567"))
    await session.flush()

    user = await UsersRepo(session).get_for_authentication(user_id, email=EMAIL, display_name=NAME)

    assert (user.email, user.display_name) == (EMAIL, NAME)


async def test_the_backfill_never_overwrites_a_value_already_there(session) -> None:
    """Fills a hole, and only a hole.

    `display_name` is the one field a seller may edit later. Overwriting on
    every request would silently revert their choice to the Google name,
    forever, with no error anywhere.
    """
    user_id = uuid.uuid4()
    session.add(User(id=user_id, email="chosen@example.com", display_name="Shop Bé Bống"))
    await session.flush()

    user = await UsersRepo(session).get_for_authentication(user_id, email=EMAIL, display_name=NAME)

    assert (user.email, user.display_name) == ("chosen@example.com", "Shop Bé Bống")


async def test_a_returning_seller_with_no_claim_keeps_a_null_email(session) -> None:
    """A seller who never returns with a verified email keeps NULL.

    Which is right: we genuinely do not know it, and #1972 is the whole lesson
    about putting a plausible value in a column instead of nothing.
    """
    user_id = uuid.uuid4()
    session.add(User(id=user_id))
    await session.flush()

    user = await UsersRepo(session).get_for_authentication(user_id)

    assert user.email is None


async def test_two_sellers_may_share_an_email(session) -> None:
    """`users.email` carries no UNIQUE constraint, deliberately.

    `users.id` is the Supabase `sub`. A seller who deletes and re-creates their
    Supabase account returns with a NEW sub and the SAME address; a unique
    index would raise inside the authentication path and lock them out of their
    own account.

    UNPROVEN HERE FOR POSTGRES -- this is SQLite. What it does prove is that
    the model declares no uniqueness, which is what the migration mirrors.
    """
    repo = UsersRepo(session)

    first = await repo.get_for_authentication(uuid.uuid4(), email=EMAIL)
    second = await repo.get_for_authentication(uuid.uuid4(), email=EMAIL)
    await session.flush()

    assert first.id != second.id
    assert (first.email, second.email) == (EMAIL, EMAIL)
    assert User.__table__.c.email.unique is not True


def test_the_email_column_is_nullable_and_wide_enough_for_any_address() -> None:
    column = User.__table__.c.email

    assert column.nullable is True
    assert column.type.length == 320, "RFC 5321's maximum address length"
