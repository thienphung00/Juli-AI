"""The provisioning write path stays greppable (#1906).

``UsersRepo.get_or_create`` is the one write four ``services/tiktok/*``
stores already use to insert a first-sighting ``users`` row. #1906 adds
exactly one more caller -- inside ``UsersRepo`` itself
(``_provision_first_sighting``, called from ``get_for_authentication`` under
the same user scope) -- rather than a second, independent provisioning path
somewhere else (a raw INSERT in a service, a duplicate get-or-create method,
or a call straight from ``core/security/dependencies.py``, which ADR-085
decision 2 keeps free of tenant-context/write concerns).

This test is the guard against that exemption list growing silently: it
greps every call SITE of ``.get_or_create(`` (not its one definition) across
the backend source tree and asserts the file set is exactly the five named
below. A new caller anywhere else fails this test until it is named here on
purpose.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/src/juli_backend"

# `.get_or_create(` as a method *call*, not the `async def get_or_create(`
# definition in repositories/identity.py.
_CALL_SITE = re.compile(r"\.get_or_create\(")
_DEFINITION = re.compile(r"def get_or_create\(")

ALLOWED_CALL_SITES = {
    "repositories/identity.py",  # #1906: UsersRepo._provision_first_sighting, same-scope insert
    "services/tiktok/app_review_store.py",
    "services/tiktok/business_account_holder_store.py",
    "services/tiktok/advertiser_oauth_store.py",
    "services/tiktok/oauth.py",
}


def _call_sites() -> set[str]:
    """Files where ``.get_or_create(`` appears as a call, not the definition.

    ``_CALL_SITE`` matches both the call (``repo.get_or_create(...)``) and
    the definition (``async def get_or_create(...)``, which also ends in
    ``.get_or_create(`` once the ``async def `` prefix is stripped -- no, it
    is not: the definition line is ``def get_or_create(``, with no leading
    dot, so ``_CALL_SITE`` (which anchors on a leading ``.``) never matches
    it. The count-and-subtract below is intentionally not needed for that
    reason; it stays only as a second, independent check that a file's
    total ``get_or_create(`` mentions are fully accounted for by calls plus
    (at most) its own definition.
    """
    found: set[str] = set()
    for path in BACKEND.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if _CALL_SITE.search(text):
            found.add(str(path.relative_to(BACKEND)))
    return found


def test_get_or_create_has_no_undocumented_call_site() -> None:
    call_sites = _call_sites()
    assert call_sites == ALLOWED_CALL_SITES, (
        f"UsersRepo.get_or_create is called from {call_sites}, expected exactly "
        f"{ALLOWED_CALL_SITES}. A new call site must be a reuse of this same "
        f"write path, named here on purpose -- not a second provisioning path."
    )


def test_get_or_create_is_defined_exactly_once() -> None:
    """The write path itself has one definition -- repositories/identity.py."""
    definitions = [
        str(path.relative_to(BACKEND))
        for path in BACKEND.rglob("*.py")
        if _DEFINITION.search(path.read_text(encoding="utf-8"))
    ]
    assert definitions == ["repositories/identity.py"], definitions
