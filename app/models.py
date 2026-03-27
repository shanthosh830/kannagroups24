from __future__ import annotations

import enum
import math
import secrets
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager


class Role(str, enum.Enum):
    OWNER = "owner"
    DIGITIZER = "digitizer"


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(32), nullable=False, default=Role.OWNER.value)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(64), unique=True, nullable=False)
    name_en = db.Column(db.String(128), nullable=False)
    name_ta = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    designs = db.relationship("Design", backref="service", lazy=True)


class Design(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey("service.id"), nullable=False)

    # Optional subcategory within a service (e.g. chudi, blouse, bridal blouse)
    subcategory = db.Column(db.String(64), nullable=True)

    title_en = db.Column(db.String(200), nullable=False)
    title_ta = db.Column(db.String(200), nullable=False)
    # Pricing is auto-calculated based on stitches per selected area(s).
    # `min_price_inr` is a cached "From ₹X" used for shop filters/sorting.
    min_price_inr = db.Column(db.Integer, nullable=True)

    # Optional manual fixed price (in INR). If set and >0, this will be used instead of auto-calculated price.
    manual_price_inr = db.Column(db.Integer, nullable=True)

    # Optional design/digitizing charge, applied only when configured.
    design_charge_inr = db.Column(db.Integer, nullable=True)
    design_charge_first_order_only = db.Column(db.Boolean, nullable=False, default=True)
    design_charge_applied_once = db.Column(db.Boolean, nullable=False, default=False)

    # For "New Arrivals" tab (admin mark)
    is_new_arrival = db.Column(db.Boolean, nullable=False, default=False)

    image_filename = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    stitches = db.relationship(
        "DesignStitches", backref="design", uselist=False, lazy=True, cascade="all, delete-orphan"
    )


class DesignStitches(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    design_id = db.Column(db.Integer, db.ForeignKey("design.id"), unique=True, nullable=False)

    # Enable/disable area options for this design
    enable_fn = db.Column(db.Boolean, nullable=False, default=True)  # Front Neck
    enable_bn = db.Column(db.Boolean, nullable=False, default=True)  # Back Neck
    enable_sl = db.Column(db.Boolean, nullable=False, default=True)  # Single Sleeve (×2 in calc)
    enable_bn_butta = db.Column(db.Boolean, nullable=False, default=False)
    enable_sl_butta = db.Column(db.Boolean, nullable=False, default=False)

    # Stitches per option (customers never see these)
    stitches_fn = db.Column(db.Integer, nullable=False, default=0)
    stitches_bn = db.Column(db.Integer, nullable=False, default=0)
    stitches_sl_single = db.Column(db.Integer, nullable=False, default=0)
    stitches_bn_butta = db.Column(db.Integer, nullable=False, default=0)
    stitches_sl_butta_single = db.Column(db.Integer, nullable=False, default=0)

    # Per-area manual prices (₹). If set > 0, used instead of stitch-based calc for that area.
    price_fn = db.Column(db.Integer, nullable=True)
    price_bn = db.Column(db.Integer, nullable=True)
    price_sl = db.Column(db.Integer, nullable=True)
    price_bn_butta = db.Column(db.Integer, nullable=True)
    price_sl_butta = db.Column(db.Integer, nullable=True)


def _get_int_setting(key: str, default: int) -> int:
    raw = get_setting(key, str(default))
    try:
        return int(raw)
    except Exception:
        return default


def calc_price_inr_for_selection(design: Design, selected: list[str]) -> int:
    """
    Calculate price for a design based on selected areas.
    selected keys: fn, bn, sl, bn_butta, sl_butta
    
    Priority:
    1. If manual_price_inr is set → use flat price regardless of selection
    2. If per-area prices are set → sum selected area prices
    3. Else → calculate from stitch counts
    """
    # Priority 1: Manual fixed price override
    if design.manual_price_inr and design.manual_price_inr > 0:
        return int(design.manual_price_inr)

    if not design.stitches:
        return 0

    ds = design.stitches

    # Priority 2: Per-area manual prices (sum of selected areas)
    area_price_map = {
        "fn": (ds.enable_fn, ds.price_fn),
        "bn": (ds.enable_bn, ds.price_bn),
        "sl": (ds.enable_sl, ds.price_sl),
        "bn_butta": (ds.enable_bn_butta, ds.price_bn_butta),
        "sl_butta": (ds.enable_sl_butta, ds.price_sl_butta),
    }
    has_any_area_price = any(p and p > 0 for _, p in area_price_map.values())
    
    if has_any_area_price:
        total = 0
        for key in selected:
            if key in area_price_map:
                enabled, price = area_price_map[key]
                if enabled and price and price > 0:
                    total += price
        # Apply customer markup if configured
        markup_percent = _get_int_setting("customer_markup_percent", 0)
        if markup_percent and total > 0:
            total = math.ceil(total * (1 + (markup_percent / 100)))
        return max(0, total)

    # Priority 3: Stitch-based calculation
    threshold = _get_int_setting("stitch_threshold", 15000)
    rate_amount = _get_int_setting("rate_amount", 100)
    sleeve_multiplier = _get_int_setting("sleeve_multiplier", 2)

    total_stitches = 0

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

    # Design charge rule
    if design.design_charge_inr and design.design_charge_inr > 0:
        if not design.design_charge_first_order_only or not design.design_charge_applied_once:
            base_price += int(design.design_charge_inr)

    # Apply customer markup
    markup_percent = _get_int_setting("customer_markup_percent", 0)
    if markup_percent and base_price > 0:
        base_price = math.ceil(base_price * (1 + (markup_percent / 100)))

    return max(0, base_price)


def recompute_design_min_price(design: Design) -> None:
    # If manual fixed price is set, use it as the minimum.
    if design.manual_price_inr and design.manual_price_inr > 0:
        design.min_price_inr = int(design.manual_price_inr)
        return

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


class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)


# Order status: pending_payment -> (customer submits payment) -> pending_approval -> (admin marks) -> paid -> processing -> completed
ORDER_STATUS_PENDING_PAYMENT = "pending_payment"
ORDER_STATUS_PENDING_APPROVAL = "pending_approval"
ORDER_STATUS_PAID = "paid"
ORDER_STATUS_PROCESSING = "processing"
ORDER_STATUS_DELIVERED = "delivered"
ORDER_STATUS_COMPLETED = "completed"
ORDER_STATUS_CANCELLED = "cancelled"


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)  # for customer view without login

    customer_name = db.Column(db.String(200), nullable=False)
    customer_phone = db.Column(db.String(32), nullable=False)
    customer_email = db.Column(db.String(255), nullable=True)
    address = db.Column(db.Text, nullable=False)

    total_inr = db.Column(db.Integer, nullable=False)
    order_type = db.Column(db.String(32), nullable=False, default="customer")  # customer or tailor
    referral_code = db.Column(db.String(64), nullable=True)  # code used by this order to get discount
    referred_by_order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=True)
    referral_discount_inr = db.Column(db.Integer, nullable=True)
    referral_reward_used = db.Column(db.Boolean, nullable=False, default=False)

    status = db.Column(db.String(32), nullable=False, default=ORDER_STATUS_PENDING_PAYMENT)
    transaction_id = db.Column(db.String(128), nullable=True)  # customer or admin fills
    admin_notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    items = db.relationship("OrderItem", backref="order", lazy=True, cascade="all, delete-orphan")


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    design_id = db.Column(db.Integer, db.ForeignKey("design.id"), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    price_inr = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    selected_areas = db.Column(db.String(200), nullable=True)  # e.g. fn,bn,sl
    include_stitching = db.Column(db.Boolean, nullable=False, default=False)


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(200), nullable=False)
    order_code = db.Column(db.String(64), nullable=True)
    rating = db.Column(db.Integer, nullable=False)  # 1-5
    text = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(32), nullable=False, default="pending")  # pending, approved, rejected
    reply = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class CustomRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(32))
    customer_name = db.Column(db.String(200), nullable=False)
    customer_phone = db.Column(db.String(32), nullable=False)
    description = db.Column(db.Text, nullable=False)
    areas = db.Column(db.String(200), nullable=False)  # comma-separated e.g. fn,bn,sl
    image_filename = db.Column(db.String(255), nullable=True)
    payment_method = db.Column(db.String(32), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Admin sets these after reviewing
    design_amount_inr = db.Column(db.Integer, nullable=True)
    advance_inr = db.Column(db.Integer, nullable=True)  # required advance amount

    # Customer pays advance
    advance_paid_inr = db.Column(db.Integer, nullable=True)       # amount actually paid
    advance_transaction_id = db.Column(db.String(128), nullable=True)
    advance_status = db.Column(db.String(32), nullable=False, default="pending")  # pending / paid / approved

    status = db.Column(db.String(32), nullable=False, default="pending")  # pending / in_progress / completed / cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Tailor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    amount_inr = db.Column(db.Integer, nullable=False)   # cost/expense paid out
    category = db.Column(db.String(100), nullable=True)  # e.g. "Thread", "Stitching", "Bangle"
    notes = db.Column(db.Text, nullable=True)

    # Commission tracking
    expense_type = db.Column(db.String(32), nullable=False, default="expense")  # expense | commission
    vendor_name = db.Column(db.String(200), nullable=True)    # who did the outsourced work
    revenue_inr = db.Column(db.Integer, nullable=True)         # total charged to customer for this job
    commission_inr = db.Column(db.Integer, nullable=True)      # our profit = revenue - amount_inr


def ensure_default_services() -> None:
    defaults = [
        ("embroidery", "Computerized Machine Embroidery", "கம்ப்யூட்டர் எம்பிராய்டரி"),
        ("aari", "Aari Work", "ஆரி வேலை"),
        ("stitching", "Stitching Service", "தையல் சேவை"),
        ("bangles", "Customized Silk Thread Bangles", "சில்க் நூல் வளையல்கள் (கஸ்டமைஸ்)"),
        ("malai", "Wedding Malai", "திருமண மாலை"),
        ("womens-clothing", "Online Women’s Clothing", "ஆன்லைன் மகளிர் உடைகள்"),
        ("rental-jewels", "Bridal Rental Jewels", "மணமகள் வாடகை நகைகள்"),
        ("bridal-makeup", "Bridal Makeup", "மணமகள் மேக்கப்"),
    ]
    for slug, en, ta in defaults:
        exists = Service.query.filter_by(slug=slug).first()
        if not exists:
            db.session.add(Service(slug=slug, name_en=en, name_ta=ta))
    db.session.commit()


def ensure_default_settings() -> None:
    # Business identity + payment QR placeholders (admin can edit later)
    defaults = {
        "business_name": "Kanna Groups",
        "whatsapp_number": "+919344272890",
        "email": "kannagroups24@gmail.com",
        "location": "Sholinghur, Tamil Nadu, India",
        "upi_id": "your-upi-id@bank",
        "upi_qr_filename": "",
        # Stitch-based pricing defaults (editable later)
        "stitch_threshold": "15000",
        "rate_amount": "100",
        "sleeve_multiplier": "2",
        "customization_fee": "150",
        "stitching_rate": "500",
        # Markup applied to customer price (percent)
        "customer_markup_percent": "10",
        # Referral discount amount (in INR)
        "referral_discount_inr": "50",
    }
    for k, v in defaults.items():
        if not Setting.query.filter_by(key=k).first():
            db.session.add(Setting(key=k, value=v))
    db.session.commit()


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

