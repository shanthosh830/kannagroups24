from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

from .extensions import db, login_manager, csrf


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)

    # Defaults (safe for local dev)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", f"sqlite:///{Path(app.instance_path) / 'app.db'}"
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=str(Path(app.instance_path) / "uploads"),
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,  # 20MB
    )

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .routes.public import bp as public_bp
    from .routes.admin import bp as admin_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    with app.app_context():
        from . import models  # noqa: F401
        from .db_upgrade import ensure_sqlite_schema_up_to_date

        db.create_all()
        ensure_sqlite_schema_up_to_date()

        # Ensure default services exist (idempotent)
        models.ensure_default_services()
        models.ensure_default_settings()

    @app.context_processor
    def inject_globals():
        from flask import request, session

        from .models import get_setting

        out = {"business_name": get_setting("business_name", "Kanna Groups")}
        cart = session.get("cart") or []
        out["cart_count"] = sum(i.get("qty", 1) for i in cart)
        return out

    return app

