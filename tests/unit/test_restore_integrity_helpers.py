"""Unit tests for restore integrity helpers (issues #1553, #1554)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"


def test_verify_backup_size_floor():
    """Test backup size floor verification."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from safe_alembic_helpers import verify_backup_size_floor

        assert verify_backup_size_floor(1024 * 1024) is True  # 1 MB
        assert verify_backup_size_floor(2 * 1024 * 1024) is True  # 2 MB
        assert verify_backup_size_floor(512 * 1024) is False  # 512 KB
        assert verify_backup_size_floor(1024 * 1024, min_mb=2) is False  # 1 MB < 2 MB
        assert verify_backup_size_floor(2 * 1024 * 1024, min_mb=2) is True  # 2 MB >= 2 MB
    finally:
        sys.path.pop(0)


def test_verify_restored_row_counts():
    """Test restored row counts verification with floors."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from safe_alembic_helpers import verify_restored_row_counts

        # Valid case: users and shops have at least 1 row
        counts = {
            "users": 5,
            "shops": 3,
            "tiktok_credentials": 2,
            "orders": 0,  # Can be empty
            "products": 10,
            "inventory_items": 20,
            "tiktok_sync_state": 1,
        }
        is_valid, errors = verify_restored_row_counts(counts)
        assert is_valid is True
        assert errors == []

        # Invalid: users has 0 rows
        counts_no_users = counts.copy()
        counts_no_users["users"] = 0
        is_valid, errors = verify_restored_row_counts(counts_no_users)
        assert is_valid is False
        assert any("users" in err for err in errors)
        assert any("0 rows" in err for err in errors)

        # Invalid: shops has 0 rows
        counts_no_shops = counts.copy()
        counts_no_shops["shops"] = 0
        is_valid, errors = verify_restored_row_counts(counts_no_shops)
        assert is_valid is False
        assert any("shops" in err for err in errors)

        # Valid: orders can have 0 rows
        counts_no_orders = counts.copy()
        counts_no_orders["orders"] = 0
        is_valid, errors = verify_restored_row_counts(counts_no_orders)
        assert is_valid is True
    finally:
        sys.path.pop(0)
