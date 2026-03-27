from __future__ import annotations

from sqlalchemy import text

from .extensions import db


def _has_column(table: str, column: str) -> bool:
    # Use quoted table name to avoid reserved keyword issues (e.g. "order").
    rows = db.session.execute(text(f"PRAGMA table_info(\"{table}\");")).mappings().all()
    return any(r.get("name") == column for r in rows)


def _add_column(table: str, ddl: str) -> None:
    # Use quoted table name to avoid reserved keyword issues.
    db.session.execute(text(f"ALTER TABLE \"{table}\" ADD COLUMN {ddl};"))


def ensure_sqlite_schema_up_to_date() -> None:
    """
    Very small auto-upgrade helper for local SQLite development.
    This prevents 'no such column' errors when we add new fields.

    For production, we should use proper migrations (Alembic).
    """
    # Only run for SQLite
    url = str(db.engine.url)
    if not url.startswith("sqlite"):
        return

    # design table columns added over time
    if not _has_column("design", "min_price_inr"):
        _add_column("design", "min_price_inr INTEGER")
    if not _has_column("design", "manual_price_inr"):
        _add_column("design", "manual_price_inr INTEGER")
    if not _has_column("design", "subcategory"):
        _add_column("design", "subcategory TEXT")
    if not _has_column("design", "design_charge_inr"):
        _add_column("design", "design_charge_inr INTEGER")
    if not _has_column("design", "design_charge_first_order_only"):
        _add_column("design", "design_charge_first_order_only BOOLEAN NOT NULL DEFAULT 1")
    if not _has_column("design", "design_charge_applied_once"):
        _add_column("design", "design_charge_applied_once BOOLEAN NOT NULL DEFAULT 0")
    if not _has_column("design", "is_new_arrival"):
        _add_column("design", "is_new_arrival BOOLEAN NOT NULL DEFAULT 0")

    # order_item new column
    if not _has_column("order_item", "selected_areas"):
        _add_column("order_item", "selected_areas TEXT")

    # order new columns for referrals and order types
    if not _has_column("order", "order_type"):
        _add_column("order", "order_type TEXT NOT NULL DEFAULT 'customer'")
    if not _has_column("order", "referral_code"):
        _add_column("order", "referral_code TEXT")
    if not _has_column("order", "referred_by_order_id"):
        _add_column("order", "referred_by_order_id INTEGER")
    if not _has_column("order", "referral_discount_inr"):
        _add_column("order", "referral_discount_inr INTEGER")
    if not _has_column("order", "referral_reward_used"):
        _add_column("order", "referral_reward_used BOOLEAN NOT NULL DEFAULT 0")
        
    if not _has_column("order_item", "include_stitching"):
        _add_column("order_item", "include_stitching BOOLEAN NOT NULL DEFAULT 0")

    if not _has_column("custom_request", "design_amount_inr"):
        _add_column("custom_request", "design_amount_inr INTEGER")
    if not _has_column("custom_request", "advance_inr"):
        _add_column("custom_request", "advance_inr INTEGER")
    if not _has_column("custom_request", "token"):
        _add_column("custom_request", "token TEXT")
    if not _has_column("custom_request", "advance_paid_inr"):
        _add_column("custom_request", "advance_paid_inr INTEGER")
    if not _has_column("custom_request", "advance_transaction_id"):
        _add_column("custom_request", "advance_transaction_id TEXT")
    if not _has_column("custom_request", "advance_status"):
        _add_column("custom_request", "advance_status TEXT NOT NULL DEFAULT 'pending'")

    # Expense commission columns
    if not _has_column("expense", "expense_type"):
        _add_column("expense", "expense_type TEXT NOT NULL DEFAULT 'expense'")
    if not _has_column("expense", "vendor_name"):
        _add_column("expense", "vendor_name TEXT")
    if not _has_column("expense", "revenue_inr"):
        _add_column("expense", "revenue_inr INTEGER")
    if not _has_column("expense", "commission_inr"):
        _add_column("expense", "commission_inr INTEGER")

    # design_stitches per-area price columns
    for col in ("price_fn", "price_bn", "price_sl", "price_bn_butta", "price_sl_butta"):
        if not _has_column("design_stitches", col):
            _add_column("design_stitches", f"{col} INTEGER")

    # Create new tables if they don't exist
    db.create_all()

    db.session.commit()

