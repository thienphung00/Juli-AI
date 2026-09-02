"""Shared test infrastructure. Import from here instead of copying.

===============  ==========================================================
``builders``     ``make_user`` / ``make_shop`` / ``make_tenant`` / ``make_product`` /
                 ``make_order`` / ``make_order_item`` / ``make_credential`` -- persist
                 one entity with sensible, unique defaults; override what the test is about
``api``          ``build_app`` and ``authenticated_client`` -- the FastAPI app with the
                 session, current user and active shop overridden
``fakes``        ``FakeAsyncRedis`` -- in-memory async Redis with injectable failures
``postgres``     ``database_url`` / ``postgres_reachable`` / ``requires_postgres`` -- the one
                 definition of "this test needs a real database"
``clock``        ``SteppingClock`` -- a controllable ``now()`` so no test sleeps
===============  ==========================================================

Conventions the suite follows (``.cursor/skills/domain/testing-patterns/python-testing.md``
is the full text):

* A test reads as *given / when / then* with the data it cares about spelled
  out inline; everything it does not care about comes from a builder default.
* Test doubles are hand-written classes with the real method signatures, or
  the ``FakeAsyncRedis`` here. ``MagicMock()`` accepts any call, so it proves
  routing, never a contract.
* Behaviour, not implementation: assert on return values, persisted rows and
  HTTP responses. Reaching for a ``_private`` attribute is a design signal.
* ``asyncio_mode = auto``: an ``async def test_`` needs no marker.
"""
