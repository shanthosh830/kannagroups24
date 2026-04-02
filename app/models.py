from __future__ import annotations

import enum
import math
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _utcnow():
    """Timezone-aware UTC timestamp (preferred over naive datetime.utcnow)."""
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════════
# User / Auth
# ═══════════════════════════════════════════════════════════════════════

class Role(str, enum.Enum):
    OWNER = "owner"
    DIGITIZER = "digitizer"


class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(32), nullable=False, default=Role.OWNER.value)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    # Flask-Login integration
    @property
    def is_active(self):
        return True

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.email}>"


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


# ═══════════════════════════════════════════════════════════════════════
# Service / Design catalogue
# ═══════════════════════════════════════════════════════════════════════

class Service(db.Model):
    __tablename__ = "service"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name_en = db.Column(db.String(128), nullable=False)
    name_ta = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    designs = db.relationship("Design", backref="service", lazy=True,
                              cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Service {self.slug}>"


class Design(db.Model):
    __tablename__ = "design"

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey("service.id"), nullable=False, index=True)

    title_en = db.Column(db.String(200), nullable=False)
    title_ta = db.Column(db.String(200), nullable=False)

    # Cached "From ₹X" used for shop filters/sorting
    min_price_inr = db.Column(db.Integer, nullable=True)

    # Optional design/digitizing charge
    design_charge_inr = db.Column(db.Integer, nullable=True)
    design_charge_first_order_only = db.Column(db.Boolean, nullable=False, default=True)
    design_charge_applied_once = db.Column(db.Boolean, nullable=False, default=False)

    # "New Arrivals" tab flag
    is_new_arrival = db.Column(db.Boolean, nullable=False, default=False)

    # Primary / thumbnail image (Cloudinary URL)
    image_filename = db.Column(db.String(500), nullable=False, default="")

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    stitches = db.relationship(
        "DesignStitches", backref="design", uselist=False, lazy=True,
        cascade="all, delete-orphan"
    )
    images = db.relationship(
        "DesignImage", backref="design", lazy=True,
        cascade="all, delete-orphan", order_by="DesignImage.id"
    )

    def __repr__(self):
        return f"<Design {self.id} {self.title_en[:30]}>"


class DesignImage(db.Model):
    """Stores multiple Cloudinary image URLs per design."""
    __tablename__ = "design_image"

    id = db.Column(db.Integer, primary_key=True)
    design_id = db.Column(db.Integer, db.ForeignKey("design.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    image_url = db.Column(db.String(500), nullable=False)

    def __repr__(self):
        return f"<DesignImage {self.id} design={self.design_id}>"


class DesignStitches(db.Model):
    __tablename__ = "design_stitches"

    id = db.Column(db.Integer, primary_key=True)
    design_id = db.Column(db.Integer, db.ForeignKey("design.id", ondelete="CASCADE"),
                          unique=True, nullable=False)

    # Enable/disable area options
    enable_fn = db.Column(db.Boolean, nullable=False, default=True)
    enable_bn = db.Column(db.Boolean, nullable=False, default=True)
    enable_sl = db.Column(db.Boolean, nullable=False, default=True)
    enable_bn_butta = db.Column(db.Boolean, nullable=False, default=False)
    enable_sl_butta = db.Column(db.Boolean, nullable=False, default=False)

    # Stitches per option (customers never see these)
    stitches_fn = db.Column(db.Integer, nullable=False, default=0)
    stitches_bn = db.Column(db.Integer, nullable=False, default=0)
    stitches_sl_single = db.Column(db.Integer, nullable=False, default=0)
    stitches_bn_butta = db.Column(db.Integer, nullable=False, default=0)
    stitches_sl_butta_single = db.Column(db.Integer, nullable=False, default=0)


# ═══════════════════════════════════════════════════════════════════════
# Pricing logic
# ═══════════════════════════════════════════════════════════════════════

def _get_int_setting(key: str, default: int) -> int:
    raw = get_setting(key, str(default))
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def calc_price_inr_for_selection(design: Design, selected: list[str]) -> int:
    """Calculate price for a design based on selected areas."""
    if not design.stitches:
        return 0

    threshold = _get_int_setting("stitch_threshold", 15000)
    rate_amount = _get_int_setting("rate_amount", 100)
    sleeve_multiplier = _get_int_setting("sleeve_multiplier", 2)

    total_stitches = 0
    ds = design.stitches

    if "fn" in selected and ds.enable_fn:
        total_stitches += max(0, ds.stitches_fn)
    if "bn" in selected and ds.enable_bn:
        total_stitches += max(0, ds.stitches_bn)
    if "sl" in selected and ds.enable_sl:
        total_stitches += max(0, ds.stitches_sl_single) * sleeve_multiplier
    if "bn_butta" in selected and ds.enable_bn_butta:
        total_stitches += max(0, ds.stitches_bn_butta)
    if "sl_butta" in selected and ds.enable_sl_butta:
        total_stitches += max(0, ds.stitches_sl_butta_single) * sleeve_multiplier

    if threshold <= 0 or rate_amount <= 0:
        return 0
    base = (total_stitches / threshold) * rate_amount
    base_price = int(math.ceil(base))

    if design.design_charge_inr and design.design_charge_inr > 0:
        if not design.design_charge_first_order_only or not design.design_charge_applied_once:
            base_price += int(design.design_charge_inr)

    return max(0, base_price)


def recompute_design_min_price(design: Design) -> None:
    """Recompute the cached min_price_inr for shop card display."""
    if not design.stitches:
        design.min_price_inr = None
        return
    ds = design.stitches
    candidates: list[int] = []
    if ds.enable_fn:
        candidates.append(calc_price_inr_for_selection(design, ["fn"]))
    if ds.enable_bn:
        candidates.append(calc_price_inr_for_selection(design, ["bn"]))
    if ds.enable_sl:
        candidates.append(calc_price_inr_for_selection(design, ["sl"]))
    if ds.enable_bn_butta:
        candidates.append(calc_price_inr_for_selection(design, ["bn_butta"]))
    if ds.enable_sl_butta:
        candidates.append(calc_price_inr_for_selection(design, ["sl_butta"]))
    candidates = [c for c in candidates if c > 0]
    design.min_price_inr = min(candidates) if candidates else None


# ═══════════════════════════════════════════════════════════════════════
# Settings (key-value store)
# ═══════════════════════════════════════════════════════════════════════

class Setting(db.Model):
    __tablename__ = "setting"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=False)

    def __repr__(self):
        return f"<Setting {self.key}>"


def get_setting(key: str, default: str = "") -> str:
    s = Setting.query.filter_by(key=key).first()
    return s.value if s else default


def set_setting(key: str, value: str) -> None:
    s = Setting.query.filter_by(key=key).first()
    if not s:
        s = Setting(key=key, value=value)
        db.session.add(s)
    else:
        s.value = value
    db.session.commit()


# ═══════════════════════════════════════════════════════════════════════
# Orders
# ═══════════════════════════════════════════════════════════════════════

ORDER_STATUS_PENDING_PAYMENT = "pending_payment"
ORDER_STATUS_PENDING_APPROVAL = "pending_approval"
ORDER_STATUS_PAID = "paid"
ORDER_STATUS_PROCESSING = "processing"
ORDER_STATUS_COMPLETED = "completed"
ORDER_STATUS_CANCELLED = "cancelled"


class Order(db.Model):
    __tablename__ = "order"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)

    customer_name = db.Column(db.String(200), nullable=False)
    customer_phone = db.Column(db.String(32), nullable=False, index=True)
    customer_email = db.Column(db.String(255), nullable=True)
    address = db.Column(db.Text, nullable=False)

    total_inr = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(32), nullable=False, default=ORDER_STATUS_PENDING_PAYMENT, index=True)
    transaction_id = db.Column(db.String(128), nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    items = db.relationship("OrderItem", backref="order", lazy=True,
                            cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Order {self.id} {self.status}>"


class OrderItem(db.Model):
    __tablename__ = "order_item"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    design_id = db.Column(db.Integer, db.ForeignKey("design.id", ondelete="SET NULL"),
                          nullable=True)
    title = db.Column(db.String(200), nullable=False)
    price_inr = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    selected_areas = db.Column(db.String(200), nullable=True)

    def __repr__(self):
        return f"<OrderItem {self.id} order={self.order_id}>"


# ═══════════════════════════════════════════════════════════════════════
# Reviews
# ═══════════════════════════════════════════════════════════════════════

class Review(db.Model):
    __tablename__ = "review"

    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(200), nullable=False)
    order_code = db.Column(db.String(64), nullable=True)
    rating = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(32), nullable=False, default="pending", index=True)
    reply = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self):
        return f"<Review {self.id} {self.status}>"


# ═══════════════════════════════════════════════════════════════════════
# Custom Requests
# ═══════════════════════════════════════════════════════════════════════

class CustomRequest(db.Model):
    __tablename__ = "custom_request"

    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(200), nullable=False)
    customer_phone = db.Column(db.String(32), nullable=False)
    description = db.Column(db.Text, nullable=False)
    areas = db.Column(db.String(200), nullable=False)
    image_filename = db.Column(db.String(500), nullable=True)  # Cloudinary URL
    payment_method = db.Column(db.String(32), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(32), nullable=False, default="pending", index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self):
        return f"<CustomRequest {self.id} {self.status}>"


# ═══════════════════════════════════════════════════════════════════════
# Seed data (idempotent)
# ═══════════════════════════════════════════════════════════════════════

def ensure_default_services() -> None:
    defaults = [
        ("embroidery", "Computerized Machine Embroidery", "கம்ப்யூட்டர் எம்பிராய்டரி"),
        ("aari", "Aari Work", "ஆரி வேலை"),
        ("stitching", "Stitching Service", "தையல் சேவை"),
        ("bangles", "Customized Silk Thread Bangles", "சில்க் நூல் வளையல்கள் (கஸ்டமைஸ்)"),
        ("malai", "Wedding Malai", "திருமண மாலை"),
        ("womens-clothing", "Online Women's Clothing", "ஆன்லைன் மகளிர் உடைகள்"),
        ("rental-jewels", "Bridal Rental Jewels", "மணமகள் வாடகை நகைகள்"),
        ("bridal-makeup", "Bridal Makeup", "மணமகள் மேக்கப்"),
    ]
    changed = False
    for slug, en, ta in defaults:
        if not Service.query.filter_by(slug=slug).first():
            db.session.add(Service(slug=slug, name_en=en, name_ta=ta))
            changed = True
    if changed:
        db.session.commit()


def ensure_default_settings() -> None:
    defaults = {
        "business_name": "Kanna Groups",
        "whatsapp_number": "+919344272890",
        "email": "kannagroups24@gmail.com",
        "location": "Dindigul, Tamil Nadu, India",
        "upi_id": "your-upi-id@bank",
        "upi_qr_filename": "",
        "stitch_threshold": "15000",
        "rate_amount": "100",
        "sleeve_multiplier": "2",
        "customization_fee": "150",
    }
    changed = False
    for k, v in defaults.items():
        if not Setting.query.filter_by(key=k).first():
            db.session.add(Setting(key=k, value=v))
            changed = True
    if changed:
        db.session.commit()
