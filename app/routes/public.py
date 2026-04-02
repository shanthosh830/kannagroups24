from __future__ import annotations

import secrets

import cloudinary.uploader
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, session, url_for
from pathlib import Path

from ..extensions import db
from ..models import (
    CustomRequest,
    Design,
    Order,
    OrderItem,
    Review,
    Service,
    calc_price_inr_for_selection,
    get_setting,
    ORDER_STATUS_PENDING_APPROVAL,
    ORDER_STATUS_PENDING_PAYMENT,
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
    return sum(item["price_inr"] * item["qty"] for item in cart_list)


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
        from datetime import datetime, timedelta

        cutoff = datetime.utcnow() - timedelta(days=14)
        new_arrivals = [
            d for d in designs if d.is_new_arrival or (d.created_at and d.created_at >= cutoff)
        ]
        return render_template(
            "shop/embroidery.html",
            service=service,
            tab=tab,
            designs=designs,
            new_arrivals=new_arrivals,
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
    return {"price_inr": price}


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
    cart_list = _get_cart()
    for item in cart_list:
        if item["design_id"] == design_id and item.get("areas") == ",".join(selected_areas):
            item["qty"] += qty
            _set_cart(cart_list)
            flash("Cart updated.", "success")
            return redirect(request.referrer or url_for("public.shop"))
    cart_list.append({
        "item_id": secrets.token_hex(8),
        "design_id": design_id,
        "qty": qty,
        "title_en": design.title_en,
        "title_ta": design.title_ta,
        "price_inr": price,
        "image_filename": design.image_filename,
        "areas": ",".join(selected_areas),
    })
    _set_cart(cart_list)
    flash("Added to cart.", "success")
    return redirect(request.referrer or url_for("public.shop"))


@bp.post("/cart/add-custom")
def cart_add_custom():
    service_slug = request.form.get("service_slug")
    if service_slug == "stitching":
        stype = request.form.get("stitching_type")
        lopt = request.form.get("lining_option")
        key = f"stitching_{stype}_{lopt}"
        price_str = get_setting(key, "")
        try:
            price_inr = int(price_str)
        except ValueError:
            price_inr = 0
        if price_inr <= 0:
            flash("Pricing not configured for this option. Please contact us.", "error")
            return redirect(request.referrer or url_for("public.shop"))
        
        name_en = f"Stitching Service ({stype.title()} - {lopt.replace('_', ' ').title()})"
        name_ta = f"தையல் சேவை ({stype} - {lopt})"
        
        cart_list = _get_cart()
        # Ensure older items have item_id
        for i in cart_list:
            if "item_id" not in i:
                i["item_id"] = secrets.token_hex(8)

        cart_list.append({
            "item_id": secrets.token_hex(8),
            "design_id": None,
            "qty": 1,
            "title_en": name_en,
            "title_ta": name_ta,
            "price_inr": price_inr,
            "image_filename": "",
            "areas": "",
        })
        _set_cart(cart_list)
        flash("Added to cart.", "success")
        return redirect(url_for("public.cart_page"))
    
    return redirect(url_for("public.shop"))


@bp.post("/cart/remove")
def cart_remove():
    item_id = request.form.get("item_id")
    design_id = request.form.get("design_id", type=int)
    
    cart_list = _get_cart()
    if item_id:
        cart_list = [i for i in cart_list if i.get("item_id") != item_id]
    elif design_id is not None:
        cart_list = [i for i in cart_list if i.get("design_id") != design_id]
        
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
    total = _cart_total(cart_list)
    token = secrets.token_urlsafe(32)
    order = Order(
        token=token,
        customer_name=form.customer_name.data.strip(),
        customer_phone=form.customer_phone.data.strip(),
        customer_email=(form.customer_email.data or "").strip() or None,
        address=form.address.data.strip(),
        total_inr=total,
        status=ORDER_STATUS_PENDING_PAYMENT,
    )
    db.session.add(order)
    db.session.flush()
    for item in cart_list:
        oi = OrderItem(
            order_id=order.id,
            design_id=item["design_id"],
            title=item["title_en"],
            price_inr=item["price_inr"],
            quantity=item["qty"],
            selected_areas=item.get("areas"),
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
    order.transaction_id = txn_id or None
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
        result = cloudinary.uploader.upload(f, folder="kannagroups/custom")
        image_filename = result["secure_url"]
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

