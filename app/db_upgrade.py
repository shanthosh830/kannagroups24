from __future__ import annotations

from sqlalchemy import text

from .extensions import db


def _has_column(table: str, column: str) -> bool:
    rows = db.session.execute(text(f"PRAGMA table_info({table});")).mappings().all()
    return any(r.get("name") == column for r in rows)


def _add_column(table: str, ddl: str) -> None:
    db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl};"))


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
    if not _has_column("design", "design_charge_inr"):
        _add_column("design", "design_charge_inr INTEGER")
    if not _has_column("design", "design_charge_first_order_only"):
        _add_column("design", "design_charge_first_order_only BOOLEAN NOT NULL DEFAULT 1")
    if not _has_column("design", "design_charge_applied_once"):
        _add_column("design", "design_charge_applied_once BOOLEAN NOT NULL DEFAULT 0")
    if not _has_column("design", "is_new_arrival"):
        _add_column("design", "is_new_arrival BOOLEAN NOT NULL DEFAULT 0")
    if not _has_column("design", "stitching_charge_inr"):
        _add_column("design", "stitching_charge_inr INTEGER")

    # order_item new column
    if not _has_column("order_item", "selected_areas"):
        _add_column("order_item", "selected_areas TEXT")

    db.session.commit()

