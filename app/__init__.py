from __future__ import annotations

import os
from pathlib import Path

import cloudinary
from flask import Flask

from .extensions import csrf, db, login_manager

# ── Cloudinary configuration ──────────────────────────────────────────
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME", "your_cloud_name"),
    api_key=os.environ.get("CLOUDINARY_API_KEY", "your_api_key"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET", "your_api_secret"),
)


def _resolve_database_url(app: Flask) -> str:
    """
    Resolve DATABASE_URL with production-safe defaults.

    - Heroku / Render set postgres:// which SQLAlchemy 1.4+ rejects;
      rewrite to postgresql://.
    - Falls back to local SQLite for development.
    """
    url = os.environ.get("DATABASE_URL", "")
    if url:
        # Heroku / Render compatibility
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    # Local dev fallback
    return f"sqlite:///{Path(app.instance_path) / 'app.db'}"


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)

    db_url = _resolve_database_url(app)
    is_sqlite = db_url.startswith("sqlite")

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        SQLALCHEMY_DATABASE_URI=db_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        # ── Connection-pool tuning (ignored by SQLite) ────────────
        SQLALCHEMY_ENGINE_OPTIONS={
            "pool_recycle": 280,       # recycle connections before server timeout
            "pool_pre_ping": True,     # verify connections are alive before use
        },
        UPLOAD_FOLDER=str(Path(app.instance_path) / "uploads"),
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,  # 20 MB
    )

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)

    # ── Blueprints ────────────────────────────────────────────────
    from .routes.public import bp as public_bp
    from .routes.admin import bp as admin_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    # ── Database bootstrap ────────────────────────────────────────
    with app.app_context():
        from . import models  # noqa: F401

        db.create_all()

        # SQLite-only lightweight schema patcher (dev convenience)
        if is_sqlite:
            from .db_upgrade import ensure_sqlite_schema_up_to_date
            ensure_sqlite_schema_up_to_date()

        # Seed default data (idempotent)
        models.ensure_default_services()
        models.ensure_default_settings()

    # ── Template globals ──────────────────────────────────────────
    @app.context_processor
    def inject_globals():
        from flask import url_for, session
        from .models import get_setting

        def img_url(filename):
            """Return Cloudinary URL directly, or fall back to local uploads route."""
            if not filename:
                return ""
            if filename.startswith(("http://", "https://")):
                return filename
            return url_for("public.uploads", filename=filename)

        out = {
            "business_name": get_setting("business_name", "Kanna Groups"),
            "img_url": img_url,
        }
        cart = session.get("cart") or []
        out["cart_count"] = sum(i.get("qty", 1) for i in cart)
        return out

    return app
