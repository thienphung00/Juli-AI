"""What a verified Supabase JWT already tells us about the seller (#1973).

THE CLAIM WAS ALWAYS THERE. A Supabase access token minted from a Google
sign-in carries the seller's `email`, whether Google verified it, and their
display name -- signed, and already checked against the project's JWKS by
`verify_supabase_jwt` before anything here runs. Until this module, the
backend read exactly one field out of that payload (`sub`) and discarded the
rest; `apps/demo/src/lib/supabase-auth.ts` decodes the same token client-side
"for display only" and the server never saw it. So Juli held a UUID, a
fabricated phone (#1972) and nothing else -- no way to reach a seller, while
the landing page offers 1:1 support to five trial shops.

WHY A MODULE OF ITS OWN, BETWEEN JWT AND REPOSITORY. Two rules meet here.
`repositories/` must not learn the shape of a Supabase token -- a repository
that reaches into `payload["user_metadata"]["full_name"]` has taken on an
authentication concern it cannot test or own. And ADR-085 decision 2 keeps
`core/security/dependencies.py` free of anything but the auth decision. So the
translation from "signed token" to "what we know about this person" lives in
`core/security/`, which is the package that already owns JWT semantics, and
crosses into the repository as a small frozen value with no vendor shape left
in it.

WHAT "VERIFIED" MEANS HERE, AND WHY IT IS ENFORCED. An `email` claim on its
own is not proof: a provider can carry an address the user typed and nobody
checked, and Supabase surfaces exactly that distinction as `email_verified`.
Writing an unverified address into `users.email` would repeat #1972's mistake
in a new column -- a contactable-looking value nobody confirmed. So the email
is taken ONLY alongside a true `email_verified`; otherwise this returns
nothing and the column stays NULL, which is the honest answer.

WHERE THE FLAG LIVES. Supabase puts `email_verified` inside `user_metadata`,
and newer versions also promote it to a top-level claim. Both are read, with
the top level winning when present -- neither is guaranteed across versions,
and requiring the one that happens to be missing would silently reject every
real token.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Supabase/Google put the human-readable name under `user_metadata`, with
#: `full_name` the populated one for a Google identity and `name` the fallback
#: other providers use. First non-empty wins.
_NAME_CLAIMS = ("full_name", "name")

#: RFC 5321's maximum address length. `users.display_name` is String(100), so
#: a longer name is truncated rather than dropped -- a shortened name is still
#: the seller's name, where a missing one is nothing.
_MAX_EMAIL = 320
_MAX_DISPLAY_NAME = 100


@dataclass(frozen=True)
class VerifiedIdentity:
    """What the token proves about the seller, with no vendor shape left.

    Both fields are optional on purpose. A provider that carries no name, or an
    email Google has not verified, leaves the corresponding column NULL -- the
    state `users.phone` could not express before #1972 and the reason this
    codebase had to invent data in the first place.
    """

    email: str | None = None
    display_name: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.email is None and self.display_name is None


def _text(value: object, *, limit: int) -> str | None:
    """A non-empty string, trimmed to `limit`, or None for anything else."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:limit]


def _metadata(payload: dict) -> dict:
    metadata = payload.get("user_metadata")
    return metadata if isinstance(metadata, dict) else {}


def _email_is_verified(payload: dict) -> bool:
    """True only for an explicit affirmative, wherever the flag is carried.

    `True` and the string `"true"` are both accepted because Supabase has
    emitted each; anything else -- absent, false, null, a string that is not
    "true" -- is not a verification and is treated as one.
    """
    metadata = _metadata(payload)
    for source in (payload, metadata):
        if "email_verified" not in source:
            continue
        flag = source["email_verified"]
        if isinstance(flag, bool):
            return flag
        if isinstance(flag, str):
            return flag.strip().lower() == "true"
        return False
    return False


def verified_identity(payload: dict) -> VerifiedIdentity:
    """Read the seller's verified email and display name out of a checked JWT.

    `payload` must be the return value of `verify_supabase_jwt` -- a payload
    whose signature, audience and expiry have already been checked. Nothing in
    here re-validates the token, and nothing in here should ever be handed an
    unverified decode.

    The display name is taken regardless of `email_verified`: it is a label
    shown back to the seller, not a channel anyone can be contacted on, so a
    name the provider did not verify costs nothing and greeting someone by the
    name they chose is the whole point. The email is gated, because that one is
    a way to reach a person.
    """
    email = None
    if _email_is_verified(payload):
        metadata = _metadata(payload)
        email = _text(payload.get("email"), limit=_MAX_EMAIL) or _text(
            metadata.get("email"), limit=_MAX_EMAIL
        )

    metadata = _metadata(payload)
    display_name = None
    for claim in _NAME_CLAIMS:
        display_name = _text(metadata.get(claim), limit=_MAX_DISPLAY_NAME)
        if display_name is not None:
            break

    return VerifiedIdentity(email=email, display_name=display_name)
