from __future__ import annotations

import math
import secrets
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import (
    CustomRequest,
    Design,
    DesignStitches,
    Order,
    OrderItem,
    Review,
    Service,
    calc_price_inr_for_selection,
    get_setting,
    ORDER_STATUS_PENDING_APPROVAL,
    ORDER_STATUS_PENDING_PAYMENT,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_DELIVERED,
    ORDER_STATUS_PAID,
)
from ..forms import CheckoutForm, CustomDesignForm, PaymentConfirmForm, ReviewForm

bp = Blueprint("public", __name__)

CART_KEY = "cart"


def _lang() -> str:
    lang = request.args.get("lang", "en").lower()
    return "ta" if lang == "ta" else "en"


def _get_cart():
    return session.get(CART_KEY) or []


def _set_cart(cart_list):
    session[CART_KEY] = cart_list
    session.modified = True


def _cart_total(cart_list):
    stitching_rate = int(get_setting("stitching_rate", "500"))
    total = 0
    for item in cart_list:
        subtotal = item["price_inr"] * item["qty"]
        if item.get("include_stitching"):
            subtotal += stitching_rate * item["qty"]
        total += subtotal
    return total


@bp.get("/")
def home():
    services = Service.query.order_by(Service.id.asc()).all()
    return render_template(
        "shop/home.html",
        services=services,
        lang=_lang(),
        business_name=get_setting("business_name", "Kanna Groups"),
        whatsapp=get_setting("whatsapp_number", "+919344272890"),
        location=get_setting("location", ""),
    )


@bp.get("/services")
def services():
    services = Service.query.order_by(Service.id.asc()).all()
    return render_template(
        "shop/services.html",
        services=services,
        lang=_lang(),
        business_name=get_setting("business_name", "Kanna Groups"),
        whatsapp=get_setting("whatsapp_number", "+919344272890"),
    )


@bp.get("/services/<slug>")
def service_detail(slug: str):
    service = Service.query.filter_by(slug=slug).first()
    if not service:
        abort(404)
    designs = Design.query.filter_by(service_id=service.id).order_by(Design.created_at.desc()).all()
    if slug == "embroidery":
        # Tabs: custom design (separate page), our designs, new arrivals (latest uploads)
        tab = request.args.get("tab", "our")
        subcat = request.args.get("subcat", "all")

        from datetime import datetime, timedelta

        cutoff = datetime.utcnow() - timedelta(days=14)
        new_arrivals = [
            d for d in designs if d.is_new_arrival or (d.created_at and d.created_at >= cutoff)
        ]

        # Subcategory tabs inside our designs
        subcategories = sorted({(d.subcategory or "other") for d in designs})
        filtered_designs = designs
        if tab == "our" and subcat and subcat != "all":
            filtered_designs = [d for d in designs if (d.subcategory or "other") == subcat]

        return render_template(
            "shop/embroidery.html",
            service=service,
            tab=tab,
            designs=filtered_designs,
            new_arrivals=new_arrivals,
            subcategories=subcategories,
            active_subcat=subcat,
            lang=_lang(),
            business_name=get_setting("business_name", "Kanna Groups"),
            whatsapp=get_setting("whatsapp_number", "+919344272890"),
            location=get_setting("location", ""),
        )
    return render_template(
        "shop/service_detail.html",
        service=service,
        designs=designs,
        lang=_lang(),
        business_name=get_setting("business_name", "Kanna Groups"),
        whatsapp=get_setting("whatsapp_number", "+919344272890"),
        location=get_setting("location", ""),
    )


@bp.get("/my-orders")
def my_orders():
    return render_template(
        "shop/my_orders.html",
        orders=None,
        lang=_lang(),
        business_name=get_setting("business_name", "Kanna Groups"),
        whatsapp=get_setting("whatsapp_number", "+919344272890"),
        location=get_setting("location", ""),
    )


@bp.post("/my-orders")
def my_orders_post():
    phone = (request.form.get("phone") or "").strip()
    if not phone:
        flash("Enter your phone number.", "error")
        return redirect(url_for("public.my_orders"))
    orders = Order.query.filter(Order.customer_phone == phone).order_by(Order.created_at.desc()).all()
    if not orders:
        flash("No orders found for this number.", "info")
    return render_template(
        "shop/my_orders.html",
        orders=orders,
        phone=phone,
        lang=_lang(),
        business_name=get_setting("business_name", "Kanna Groups"),
        whatsapp=get_setting("whatsapp_number", "+919344272890"),
        location=get_setting("location", ""),
    )


@bp.get("/design/<int:design_id>")
def design_detail(design_id: int):
    design = Design.query.get_or_404(design_id)
    service = Service.query.get(design.service_id)
    return render_template(
        "shop/design_detail.html",
        design=design,
        service=service,
        options=design.stitches,
        lang=_lang(),
        business_name=get_setting("business_name", "Kanna Groups"),
        whatsapp=get_setting("whatsapp_number", "+919344272890"),
        location=get_setting("location", ""),
    )


@bp.get("/design/<int:design_id>/quote")
def design_quote(design_id: int):
    design = Design.query.get_or_404(design_id)
    areas = request.args.getlist("areas")
    price = calc_price_inr_for_selection(design, areas)
    
    stitching = request.args.get("stitching") == "yes"
    if stitching and price > 0:
        stitching_rate = int(get_setting("stitching_rate", "500"))
        price += stitching_rate
        
    return {"price_inr": price}


def _detect_user_type(phone: str, cart_qty: int = 0) -> tuple:
    """
    Detect if a phone belongs to a tailor.
    Returns (type_str, reason_str).
    Conditions (any one triggers tailor):
      1. Phone is in the registered Tailors list
      2. Phone has >= N orders in the last 30 days (N = tailor_auto_order_threshold setting)
      3. Current cart has >= B items (B = tailor_bulk_threshold setting)
    """
    from ..models import Tailor, Order
    from datetime import datetime, timedelta

    # 1. Registered tailor
    if Tailor.query.filter_by(phone=phone).first():
        return ("tailor", "registered")

    # 2. Order history check
    try:
        order_threshold = int(get_setting("tailor_auto_order_threshold", "5"))
    except Exception:
        order_threshold = 5
    try:
        days_window = int(get_setting("tailor_auto_days_window", "30"))
    except Exception:
        days_window = 30

    if order_threshold > 0:
        since = datetime.utcnow() - timedelta(days=days_window)
        recent_count = Order.query.filter(
            Order.customer_phone == phone,
            Order.created_at >= since,
        ).count()
        if recent_count >= order_threshold:
            return ("tailor", "frequent")

    # 3. Bulk cart check
    try:
        bulk_threshold = int(get_setting("tailor_bulk_threshold", "5"))
    except Exception:
        bulk_threshold = 5
    if bulk_threshold > 0 and cart_qty >= bulk_threshold:
        return ("tailor", "bulk")

    return ("customer", "")


@bp.get("/check-phone")
def check_phone():
    """Check if a phone number belongs to a tailor (registered, frequent, or bulk)."""
    phone = request.args.get("phone", "").strip()
    cart_qty = request.args.get("cart_qty", "0")
    try:
        cart_qty = int(cart_qty)
    except Exception:
        cart_qty = 0
    if not phone:
        return {"type": "customer", "reason": ""}
    user_type, reason = _detect_user_type(phone, cart_qty)
    return {"type": user_type, "reason": reason}


# ---- Shop (all designs with filters and sort) ----
@bp.get("/shop")
def shop():
    lang = _lang()
    cat = request.args.get("cat", "all")
    price_filter = request.args.get("pf", "all")
    sort = request.args.get("sort", "default")

    q = Design.query.join(Service)
    if cat != "all":
        q = q.filter(Service.slug == cat)
    designs = q.order_by(Design.created_at.desc()).all()

    # Ensure designs have their min_price calculated.
    for d in designs:
        if d.min_price_inr is None:
            from ..models import recompute_design_min_price

            recompute_design_min_price(d)
    db.session.commit()

    if price_filter != "all":
        ranges = {
            "u500": lambda p: (p or 0) < 500,
            "u1000": lambda p: (p or 0) < 1000,
            "u2000": lambda p: (p or 0) < 2000,
            "u5000": lambda p: (p or 0) < 5000,
            "5kp": lambda p: (p or 0) >= 5000,
        }
        if price_filter in ranges:
            designs = [d for d in designs if ranges[price_filter](d.min_price_inr)]

    if sort == "asc":
        designs = sorted(designs, key=lambda d: (d.min_price_inr or 0))
    elif sort == "desc":
        designs = sorted(designs, key=lambda d: (d.min_price_inr or 0), reverse=True)
    elif sort == "name":
        designs = sorted(designs, key=lambda d: (d.title_en or ""))

    services = Service.query.order_by(Service.id).all()
    return render_template(
        "shop/shop.html",
        designs=designs,
        services=services,
        lang=lang,
        business_name=get_setting("business_name", "Kanna Groups"),
        whatsapp=get_setting("whatsapp_number", "+919344272890"),
        location=get_setting("location", ""),
        cat=cat,
        price_filter=price_filter,
        sort=sort,
    )


# ---- Cart ----
@bp.get("/cart")
def cart_page():
    cart_list = _get_cart()
    total = _cart_total(cart_list)
    return render_template(
        "shop/cart.html",
        cart=cart_list,
        total=total,
        lang=_lang(),
        business_name=get_setting("business_name", "Kanna Groups"),
        whatsapp=get_setting("whatsapp_number", "+919344272890"),
        location=get_setting("location", ""),
    )


@bp.post("/cart/add")
def cart_add():
    design_id = request.form.get("design_id", type=int)
    qty = request.form.get("qty", 1, type=int)
    selected_areas = request.form.getlist("areas")
    if not design_id or qty < 1:
        flash("Invalid request.", "error")
        return redirect(request.referrer or url_for("public.shop"))
    design = Design.query.get_or_404(design_id)
    price = calc_price_inr_for_selection(design, selected_areas)
    if price <= 0:
        flash("This design pricing is not configured yet. Please contact us.", "error")
        return redirect(url_for("public.design_detail", design_id=design_id))
    include_stitching = request.form.get("stitching") == "yes"
    cart_list = _get_cart()
    for item in cart_list:
        if item["design_id"] == design_id and item.get("areas") == ",".join(selected_areas) and item.get("include_stitching") == include_stitching:
            item["qty"] += qty
            _set_cart(cart_list)
            flash("Cart updated.", "success")
            return redirect(request.referrer or url_for("public.shop"))
    cart_list.append({
        "design_id": design_id,
        "qty": qty,
        "title_en": design.title_en,
        "title_ta": design.title_ta,
        "price_inr": price,
        "image_filename": design.image_filename,
        "areas": ",".join(selected_areas),
        "include_stitching": include_stitching,
    })
    _set_cart(cart_list)
    flash("Added to cart.", "success")
    return redirect(request.referrer or url_for("public.shop"))


@bp.post("/cart/remove")
def cart_remove():
    design_id = request.form.get("design_id", type=int)
    if design_id is None:
        return redirect(url_for("public.cart_page"))
    cart_list = [i for i in _get_cart() if i["design_id"] != design_id]
    _set_cart(cart_list)
    flash("Item removed.", "info")
    return redirect(url_for("public.cart_page"))


@bp.get("/checkout")
def checkout():
    cart_list = _get_cart()
    if not cart_list:
        flash("Cart is empty.", "error")
        return redirect(url_for("public.shop"))
    total = _cart_total(cart_list)
    form = CheckoutForm()
    return render_template(
        "shop/checkout.html",
        cart=cart_list,
        total=total,
        form=form,
        lang=_lang(),
        business_name=get_setting("business_name", "Kanna Groups"),
        whatsapp=get_setting("whatsapp_number", "+919344272890"),
        location=get_setting("location", ""),
    )


@bp.post("/checkout")
def checkout_post():
    cart_list = _get_cart()
    if not cart_list:
        flash("Cart is empty.", "error")
        return redirect(url_for("public.shop"))

    form = CheckoutForm()
    if not form.validate_on_submit():
        total = _cart_total(cart_list)
        return render_template(
            "shop/checkout.html",
            cart=cart_list,
            total=total,
            form=form,
            lang=_lang(),
            business_name=get_setting("business_name", "Kanna Groups"),
            whatsapp=get_setting("whatsapp_number", "+919344272890"),
            location=get_setting("location", ""),
        ), 400

    # Prevent placing a new order if there are previous orders not yet completed/cancelled.
    prev = Order.query.filter(
        Order.customer_phone == form.customer_phone.data.strip(),
        Order.status.notin_([ORDER_STATUS_COMPLETED, ORDER_STATUS_CANCELLED, ORDER_STATUS_DELIVERED]),
    ).first()
    if prev:
        flash(
            "You have an existing order that is not yet completed. Please wait until it is processed or contact us.",
            "error",
        )
        return redirect(url_for("public.my_orders"))

    customer_phone = form.customer_phone.data.strip()
    cart_qty = sum(item.get("qty", 1) for item in cart_list)
    order_type, _reason = _detect_user_type(customer_phone, cart_qty)

    # If tailor order, revert customer markup from cart prices
    # Wait, instead of mutating cart_list in-place (which might be confusing), we do it for total and order items.
    if order_type == "tailor":
        try:
            markup_percent = int(get_setting("customer_markup_percent", "0") or 0)
        except Exception:
            markup_percent = 0
        if markup_percent and markup_percent > 0:
            for item in cart_list:
                item_price = item.get("price_inr", 0)
                # Derive base price from markup-adjusted price.
                base_price = math.ceil(item_price / (1 + markup_percent / 100))
                item["price_inr"] = max(0, base_price)

    total = _cart_total(cart_list)

    # Apply referral discount based on unused referrals generated by this customer
    # i.e., other paid orders where referral_code == this customer's token
    try:
        referral_discount_val = int(get_setting("referral_discount_inr", "50"))
    except Exception:
        referral_discount_val = 50

    my_past_orders = Order.query.filter_by(customer_phone=customer_phone, status=ORDER_STATUS_PAID).all()
    my_tokens = [o.token for o in my_past_orders]
    
    referral_discount = 0
    used_referrals = []
    if my_tokens and referral_discount_val > 0:
        unused_refs = Order.query.filter(
            Order.referral_code.in_(my_tokens),
            Order.status == ORDER_STATUS_PAID,
            Order.referral_reward_used == False
        ).all()
        for ref in unused_refs:
            if total_after_discount >= referral_discount_val:
                referral_discount += referral_discount_val
                used_referrals.append(ref)
            else:
                break # Not enough total to use another coupon

    total_after_discount = max(0, total - referral_discount)

    token = secrets.token_urlsafe(32)
    # the referral_code requested by user during THIS checkout
    referral_code_used = (form.referral_code.data or "").strip() or None
    
    # Optional logic: make sure they aren't using their own code
    if referral_code_used and referral_code_used in my_tokens:
        flash("You cannot use your own referral code.", "error")
        return redirect(url_for("public.checkout"))

    order = Order(
        token=token,
        customer_name=form.customer_name.data.strip(),
        customer_phone=customer_phone,
        customer_email=(form.customer_email.data or "").strip() or None,
        address=form.address.data.strip(),
        total_inr=total_after_discount,
        order_type=order_type,
        referral_code=referral_code_used,
        referral_discount_inr=referral_discount if referral_discount > 0 else None,
        status=ORDER_STATUS_PENDING_PAYMENT,
    )
    db.session.add(order)
    db.session.flush()

    for ref in used_referrals:
        ref.referral_reward_used = True
    for item in cart_list:
        oi = OrderItem(
            order_id=order.id,
            design_id=item["design_id"],
            title=item["title_en"],
            price_inr=item["price_inr"],
            quantity=item["qty"],
            selected_areas=item.get("areas"),
            include_stitching=item.get("include_stitching", False),
        )
        db.session.add(oi)
    db.session.commit()
    _set_cart([])
    return redirect(url_for("public.payment", token=token))


@bp.get("/order/<token>/payment")
def payment(token: str):
    order = Order.query.filter_by(token=token).first_or_404()
    if order.status != ORDER_STATUS_PENDING_PAYMENT:
        return redirect(url_for("public.order_status", token=token))
    form = PaymentConfirmForm()
    upi_id = get_setting("upi_id", "")
    upi_qr_filename = get_setting("upi_qr_filename", "")
    return render_template(
        "shop/payment.html",
        order=order,
        form=form,
        upi_id=upi_id,
        upi_qr_filename=upi_qr_filename,
        lang=_lang(),
        business_name=get_setting("business_name", "Kanna Groups"),
        whatsapp=get_setting("whatsapp_number", "+919344272890"),
        location=get_setting("location", ""),
    )


@bp.post("/order/<token>/payment")
def payment_post(token: str):
    order = Order.query.filter_by(token=token).first_or_404()
    if order.status != ORDER_STATUS_PENDING_PAYMENT:
        flash("Order already processed.", "info")
        return redirect(url_for("public.order_status", token=token))
    txn_id = (request.form.get("transaction_id") or "").strip()
    if not txn_id:
        flash("Transaction ID is required.", "error")
        return redirect(url_for("public.payment", token=token))
    order.transaction_id = txn_id
    order.status = ORDER_STATUS_PENDING_APPROVAL
    db.session.commit()
    flash("Thank you. We will confirm your payment shortly. You can check status below.", "success")
    return redirect(url_for("public.order_status", token=token))


@bp.get("/order/<token>")
def order_status(token: str):
    order = Order.query.filter_by(token=token).first_or_404()
    return render_template(
        "shop/order_status.html",
        order=order,
        lang=_lang(),
        business_name=get_setting("business_name", "Kanna Groups"),
        whatsapp=get_setting("whatsapp_number", "+919344272890"),
        location=get_setting("location", ""),
    )


# ---- Custom Design ----
@bp.get("/custom-design")
def custom_design():
    form = CustomDesignForm()
    return render_template(
        "shop/custom_design.html",
        form=form,
        lang=_lang(),
        business_name=get_setting("business_name", "Kanna Groups"),
        whatsapp=get_setting("whatsapp_number", "+919344272890"),
        location=get_setting("location", ""),
    )


@bp.post("/custom-design")
def custom_design_post():
    form = CustomDesignForm()
    areas_list = request.form.getlist("areas")
    areas_str = ",".join(areas_list) if areas_list else ""
    image_filename = None
    if form.image.data and form.image.data.filename:
        f = form.image.data
        ext = Path(secure_filename(f.filename)).suffix.lower()
        image_filename = secrets.token_hex(8) + ext
        f.save(Path(current_app.config["UPLOAD_FOLDER"]) / image_filename)
    req = CustomRequest(
        customer_name=form.customer_name.data.strip(),
        customer_phone=form.customer_phone.data.strip(),
        description=form.description.data.strip(),
        areas=areas_str,
        image_filename=image_filename,
        payment_method=request.form.get("payment_method", "upi"),
        notes=(form.notes.data or "").strip() or None,
        status="pending",
    )
    db.session.add(req)
    db.session.commit()
    flash("Custom design request submitted. We will contact you via WhatsApp.", "success")
    return redirect(url_for("public.custom_design"))


# ---- Reviews ----
@bp.get("/reviews")
def reviews_page():
    approved = Review.query.filter_by(status="approved").order_by(Review.created_at.desc()).all()
    form = ReviewForm()
    return render_template(
        "shop/reviews.html",
        reviews=approved,
        form=form,
        lang=_lang(),
        business_name=get_setting("business_name", "Kanna Groups"),
        whatsapp=get_setting("whatsapp_number", "+919344272890"),
        location=get_setting("location", ""),
    )


@bp.post("/reviews")
def reviews_post():
    form = ReviewForm()
    if not form.validate_on_submit() or not (1 <= form.rating.data <= 5):
        flash("Please fill name, rating (1-5), and review text.", "error")
        return redirect(url_for("public.reviews_page"))
    r = Review(
        customer_name=form.customer_name.data.strip(),
        order_code=(form.order_code.data or "").strip() or None,
        rating=form.rating.data,
        text=form.text.data.strip(),
        status="pending",
    )
    db.session.add(r)
    db.session.commit()
    flash("Review submitted. It will appear after approval.", "success")
    return redirect(url_for("public.reviews_page"))


# ---- About ----
@bp.get("/about")
def about():
    return render_template(
        "shop/about.html",
        lang=_lang(),
        business_name=get_setting("business_name", "Kanna Groups"),
        whatsapp=get_setting("whatsapp_number", "+919344272890"),
        location=get_setting("location", ""),
        email=get_setting("email", ""),
    )


@bp.get("/uploads/<path:filename>")
def uploads(filename: str):
    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    return send_from_directory(upload_folder, filename)

