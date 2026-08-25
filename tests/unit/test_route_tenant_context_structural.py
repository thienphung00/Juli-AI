"""Structural test: all routes must use get_active_shop_with_context (issue #1327).

Asserts that every route handler that depends on shop resolution uses the
tenant-context-setting variant, preventing accidental regressions to bare
get_active_shop (which would silently disable the automatic seam).

Exemptions are W6-owned routes that will apply the swap themselves.
"""

import pathlib

ROUTES_DIR = pathlib.Path(__file__).parent.parent.parent / "backend/src/juli_backend/api/routes"

# Routes owned by W6 wave (PRD #1308): swap will be applied by W6, not here.
# Coordination note: W6 session must apply the swap before merging toward main.
W6_OWNED_EXEMPTIONS = {
    "demo_decisions.py",  # W6 owns agent workflow demo surface
}


def test_all_routes_use_context_setting_shop_dependency():
    """Structural assertion: every route using shop must use
    get_active_shop_with_context, not bare get_active_shop.

    Exemptions list is committed and cannot grow silently.
    """
    bare_get_active_shop_files = set()

    for route_file in ROUTES_DIR.glob("*.py"):
        if route_file.name == "__init__.py":
            continue

        if route_file.name in W6_OWNED_EXEMPTIONS:
            continue

        source = route_file.read_text()

        # Check for bare get_active_shop usage (not get_active_shop_with_context)
        if "from juli_backend.api.dependencies import" in source and "get_active_shop" in source:
            # This is an old-style import of bare get_active_shop (not wrapped)
            if "get_active_shop_with_context" not in source:
                bare_get_active_shop_files.add(route_file.name)

        # Also catch if someone uses bare get_active_shop in Depends() without wrapping
        if "Depends(get_active_shop)" in source and "get_active_shop_with_context" not in source:
            bare_get_active_shop_files.add(route_file.name)

    # Assert no routes use bare get_active_shop (except exempted W6 files)
    assert not bare_get_active_shop_files, (
        f"Routes using bare get_active_shop (not wrapped): {bare_get_active_shop_files}. "
        f"Use get_active_shop_with_context from tenant_context_middleware instead."
    )


def test_exemptions_list_is_exact():
    """Structural test: W6 exemptions list is exactly what exists in codebase.

    Prevents silent exemption-list drift: new exemptions must be explicitly
    added to the committed list with coordination notes.
    """
    # Verify that exempted files still use bare get_active_shop
    # (proving they were not swapped and are waiting for W6 to swap them)
    for exempted_file in W6_OWNED_EXEMPTIONS:
        exempted_path = ROUTES_DIR / exempted_file
        source = exempted_path.read_text()

        assert "get_active_shop" in source and "get_active_shop_with_context" not in source, (
            f"Exempted file {exempted_file} was modified or no longer uses bare get_active_shop. "
            f"If W6 has applied the swap, remove it from W6_OWNED_EXEMPTIONS."
        )
