from __future__ import annotations

from sqlalchemy import text, inspect

from .extensions import db


def _has_column(table: str, column: str) -> bool:
    """Check if a column exists in a table (works for both SQLite and PostgreSQL)."""
    inspector = inspect(db.engine)
    columns = [col["name"] for col in inspector.get_columns(table)]
    return column in columns


def _add_column_pg(table: str, column: str, col_type: str, default=None, nullable: bool = True) -> None:
    """Add a column using standard SQL (works for both SQLite and PostgreSQL)."""
    ddl = f'ALTER TABLE "{table}" ADD COLUMN "{column}" {col_type}'
    if default is not None:
        ddl += f" DEFAULT {default}"
    if not nullable:
        ddl += " NOT NULL"
    ddl += ";"
    db.session.execute(text(ddl))


def ensure_schema_up_to_date() -> None:
    """
    Lightweight auto-upgrade helper for both SQLite and PostgreSQL.
    Adds any missing columns that were introduced after initial table creation.
    db.create_all() only creates NEW tables — it does NOT add columns to existing ones.
    """
    # ── design table columns added over time ──
    design_columns = {
        "min_price_inr":                 ("INTEGER", None, True),
        "design_charge_inr":             ("INTEGER", None, True),
        "design_charge_first_order_only": ("BOOLEAN", "true", False),
        "design_charge_applied_once":     ("BOOLEAN", "false", False),
        "is_new_arrival":                ("BOOLEAN", "false", False),
        "stitching_charge_inr":          ("INTEGER", None, True),
        "subcategory":                   ("VARCHAR(64)", None, True),
    }

    changed = False
    for col_name, (col_type, default, nullable) in design_columns.items():
        if not _has_column("design", col_name):
            _add_column_pg("design", col_name, col_type, default, nullable)
            changed = True

    # ── order_item new column ──
    if not _has_column("order_item", "selected_areas"):
        _add_column_pg("order_item", "selected_areas", "VARCHAR(200)", None, True)
        changed = True

    if changed:
        db.session.commit()
