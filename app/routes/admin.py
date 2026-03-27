from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import (
    CustomRequest,
    Design,
    DesignStitches,
    Expense,
    Order,
    Review,
    Service,
    User,
    Tailor,
    get_setting,
    recompute_design_min_price,
    set_setting,
    ORDER_STATUS_PAID,
    ORDER_STATUS_PENDING_APPROVAL,
    ORDER_STATUS_PENDING_PAYMENT,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_DELIVERED,
)
from ..forms import (
    AdminLoginForm,
    DesignEditForm,
    DesignForm,
    DesignPricingForm,
    ExpenseForm,
    SettingsForm,
    UserCreateForm,
    TailorForm,
    AdminCustomRequestEditForm,
    CustomRequestAdvanceForm,
)

bp = Blueprint("admin", __name__)


def _ensure_owner_exists() -> None:
    # If no users exist, allow creating the first owner via /admin/bootstrap
    pass


@bp.get("/bootstrap")
def bootstrap():
    if User.query.first():
        flash("Bootstrap already completed.", "info")
        return redirect(url_for("admin.login"))
    return render_template("admin/bootstrap.html")


@bp.post("/bootstrap")
def bootstrap_post():
    if User.query.first():
        flash("Bootstrap already completed.", "info")
        return redirect(url_for("admin.login"))

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    if not email or not password or len(password) < 8:
        flash("Enter a valid email and a password (min 8 chars).", "error")
        return redirect(url_for("admin.bootstrap"))

    u = User(email=email, role="owner")
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    flash("Owner created. Please login.", "success")
    return redirect(url_for("admin.login"))


@bp.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))
    form = AdminLoginForm()
    return render_template("admin/login.html", form=form)


@bp.post("/login")
def login_post():
    form = AdminLoginForm()
    if not form.validate_on_submit():
        flash("Invalid login details.", "error")
        return render_template("admin/login.html", form=form), 400

    user = User.query.filter_by(email=form.email.data.strip().lower()).first()
    if not user or not user.check_password(form.password.data):
        flash("Invalid email or password.", "error")
        return render_template("admin/login.html", form=form), 400

    login_user(user)
    return redirect(url_for("admin.dashboard"))


@bp.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("admin.login"))


@bp.get("/")
@login_required
def dashboard():
    services = Service.query.order_by(Service.id.asc()).all()

    # Simple finance summary (revenue vs expenses)
    today = datetime.utcnow().date()
    month_start = today.replace(day=1)

    # Revenue counts paid + delivered + completed orders
    revenue_statuses = [ORDER_STATUS_PAID, ORDER_STATUS_DELIVERED, ORDER_STATUS_COMPLETED]

    total_revenue = db.session.query(func.coalesce(func.sum(Order.total_inr), 0)).filter(Order.status.in_(revenue_statuses)).scalar() or 0
    today_revenue = db.session.query(func.coalesce(func.sum(Order.total_inr), 0)).filter(
        Order.status.in_(revenue_statuses),
        func.date(Order.created_at) == today,
    ).scalar() or 0
    month_revenue = db.session.query(func.coalesce(func.sum(Order.total_inr), 0)).filter(
        Order.status.in_(revenue_statuses),
        func.date(Order.created_at) >= month_start,
    ).scalar() or 0

    total_expenses = db.session.query(func.coalesce(func.sum(Expense.amount_inr), 0)).scalar() or 0
    today_expenses = db.session.query(func.coalesce(func.sum(Expense.amount_inr), 0)).filter(
        func.date(Expense.date) == today
    ).scalar() or 0
    month_expenses = db.session.query(func.coalesce(func.sum(Expense.amount_inr), 0)).filter(
        func.date(Expense.date) >= month_start
    ).scalar() or 0
    
    # 7-day chart data
    from datetime import timedelta
    chart_labels = []
    chart_rev = []
    chart_exp = []
    for i in range(7)[::-1]:
        d = today - timedelta(days=i)
        chart_labels.append(d.strftime("%b %d"))
        r = db.session.query(func.coalesce(func.sum(Order.total_inr), 0)).filter(
            Order.status.in_(revenue_statuses),
            func.date(Order.created_at) == d
        ).scalar() or 0
        e = db.session.query(func.coalesce(func.sum(Expense.amount_inr), 0)).filter(
            func.date(Expense.date) == d
        ).scalar() or 0
        chart_rev.append(r)
        chart_exp.append(e)

    return render_template(
        "admin/dashboard.html",
        services=services,
        business_name=get_setting("business_name", "Kanna Groups"),
        total_revenue=total_revenue,
        today_revenue=today_revenue,
        month_revenue=month_revenue,
        total_expenses=total_expenses,
        today_expenses=today_expenses,
        month_expenses=month_expenses,
        chart_labels=chart_labels,
        chart_rev=chart_rev,
        chart_exp=chart_exp,
    )


@bp.get("/services/<slug>/designs")
@login_required
def designs_list(slug: str):
    service = Service.query.filter_by(slug=slug).first_or_404()
    designs = Design.query.filter_by(service_id=service.id).order_by(Design.created_at.desc()).all()
    return render_template("admin/designs_list.html", service=service, designs=designs)


@bp.post("/designs/<int:design_id>/delete")
@login_required
def design_delete(design_id: int):
    design = Design.query.get_or_404(design_id)
    service = Service.query.get(design.service_id)
    db.session.delete(design)
    db.session.commit()
    flash("Design deleted.", "success")
    return redirect(url_for('admin.designs_list', slug=service.slug))


@bp.get("/services/<slug>/designs/new")
@login_required
def design_new(slug: str):
    service = Service.query.filter_by(slug=slug).first_or_404()
    form = DesignForm()
    return render_template("admin/design_new.html", service=service, form=form)


@bp.post("/services/<slug>/designs/new")
@login_required
def design_new_post(slug: str):
    service = Service.query.filter_by(slug=slug).first_or_404()
    form = DesignForm()
    if not form.validate_on_submit():
        return render_template("admin/design_new.html", service=service, form=form), 400

    file = form.image.data
    if not file:
        flash("Image is required.", "error")
        return render_template("admin/design_new.html", service=service, form=form), 400

    filename = secure_filename(file.filename or "")
    if not filename:
        flash("Invalid filename.", "error")
        return render_template("admin/design_new.html", service=service, form=form), 400

    # Make filename unique
    ext = Path(filename).suffix.lower()
    unique = secrets.token_hex(8) + ext
    upload_path = Path(current_app.config["UPLOAD_FOLDER"]) / unique
    file.save(upload_path)

    d = Design(
        service_id=service.id,
        subcategory=form.subcategory.data or None,
        title_en=form.title_en.data.strip(),
        title_ta=form.title_ta.data.strip(),
        image_filename=unique,
    )
    db.session.add(d)
    db.session.flush()
    # Create default stitches row
    db.session.add(DesignStitches(design_id=d.id))
    db.session.commit()

    flash("Design uploaded.", "success")
    return redirect(url_for("admin.design_edit_pricing", design_id=d.id))


@bp.get("/designs/<int:design_id>/edit")
@login_required
def design_details_edit(design_id: int):
    design = Design.query.get_or_404(design_id)
    service = Service.query.get(design.service_id)
    form = DesignEditForm(
        title_en=design.title_en,
        title_ta=design.title_ta,
        subcategory=design.subcategory or ""
    )
    return render_template("admin/design_edit.html", design=design, service=service, form=form)


@bp.post("/designs/<int:design_id>/edit")
@login_required
def design_details_edit_post(design_id: int):
    design = Design.query.get_or_404(design_id)
    service = Service.query.get(design.service_id)
    form = DesignEditForm()
    if not form.validate_on_submit():
        return render_template("admin/design_edit.html", design=design, service=service, form=form), 400

    design.title_en = form.title_en.data.strip()
    design.title_ta = form.title_ta.data.strip()
    design.subcategory = form.subcategory.data or None

    file = form.image.data
    if file:
        filename = secure_filename(file.filename or "")
        if filename:
            ext = Path(filename).suffix.lower()
            unique = secrets.token_hex(8) + ext
            upload_path = Path(current_app.config["UPLOAD_FOLDER"]) / unique
            file.save(upload_path)
            design.image_filename = unique

    db.session.commit()
    flash("Design details updated.", "success")
    return redirect(url_for("admin.designs_list", slug=service.slug))


@bp.get("/designs/<int:design_id>/pricing")
@login_required
def design_edit_pricing(design_id: int):
    design = Design.query.get_or_404(design_id)
    if not design.stitches:
        ds = DesignStitches(design_id=design.id)
        db.session.add(ds)
        db.session.commit()
        design.stitches = ds
    ds = design.stitches
    form = DesignPricingForm(
        is_new_arrival="yes" if design.is_new_arrival else "no",
        enable_fn="yes" if ds.enable_fn else "no",
        enable_bn="yes" if ds.enable_bn else "no",
        enable_sl="yes" if ds.enable_sl else "no",
        enable_bn_butta="yes" if ds.enable_bn_butta else "no",
        enable_sl_butta="yes" if ds.enable_sl_butta else "no",
        stitches_fn=ds.stitches_fn,
        stitches_bn=ds.stitches_bn,
        stitches_sl_single=ds.stitches_sl_single,
        stitches_bn_butta=ds.stitches_bn_butta,
        stitches_sl_butta_single=ds.stitches_sl_butta_single,
        price_fn=ds.price_fn,
        price_bn=ds.price_bn,
        price_sl=ds.price_sl,
        price_bn_butta=ds.price_bn_butta,
        price_sl_butta=ds.price_sl_butta,
        manual_price_inr=design.manual_price_inr,
        design_charge_inr=design.design_charge_inr,
    )
    return render_template(
        "admin/design_pricing.html",
        design=design,
        form=form,
        business_name=get_setting("business_name", "Kanna Groups"),
    )


@bp.post("/designs/<int:design_id>/pricing")
@login_required
def design_edit_pricing_post(design_id: int):
    design = Design.query.get_or_404(design_id)
    if not design.stitches:
        ds = DesignStitches(design_id=design.id)
        db.session.add(ds)
        db.session.commit()
        design.stitches = ds
    form = DesignPricingForm()
    if not form.validate_on_submit():
        return render_template(
            "admin/design_pricing.html",
            design=design,
            form=form,
            business_name=get_setting("business_name", "Kanna Groups"),
        ), 400

    ds = design.stitches
    design.is_new_arrival = form.is_new_arrival.data == "yes"
    ds.enable_fn = form.enable_fn.data == "yes"
    ds.enable_bn = form.enable_bn.data == "yes"
    ds.enable_sl = form.enable_sl.data == "yes"
    ds.enable_bn_butta = form.enable_bn_butta.data == "yes"
    ds.enable_sl_butta = form.enable_sl_butta.data == "yes"

    ds.stitches_fn = max(0, int(form.stitches_fn.data or 0))
    ds.stitches_bn = max(0, int(form.stitches_bn.data or 0))
    ds.stitches_sl_single = max(0, int(form.stitches_sl_single.data or 0))
    ds.stitches_bn_butta = max(0, int(form.stitches_bn_butta.data or 0))
    ds.stitches_sl_butta_single = max(0, int(form.stitches_sl_butta_single.data or 0))

    ds.price_fn = form.price_fn.data if form.price_fn.data else None
    ds.price_bn = form.price_bn.data if form.price_bn.data else None
    ds.price_sl = form.price_sl.data if form.price_sl.data else None
    ds.price_bn_butta = form.price_bn_butta.data if form.price_bn_butta.data else None
    ds.price_sl_butta = form.price_sl_butta.data if form.price_sl_butta.data else None

    design.manual_price_inr = form.manual_price_inr.data
    design.design_charge_inr = form.design_charge_inr.data
    recompute_design_min_price(design)
    db.session.commit()

    flash("Pricing saved.", "success")
    return redirect(url_for("admin.design_edit_pricing", design_id=design.id))


@bp.get("/settings")
@login_required
def settings():
    form = SettingsForm(
        business_name=get_setting("business_name", "Kanna Groups"),
        whatsapp_number=get_setting("whatsapp_number", "+919344272890"),
        email=get_setting("email", ""),
        location=get_setting("location", ""),
        upi_id=get_setting("upi_id", ""),
        stitch_threshold=int(get_setting("stitch_threshold", "15000")),
        rate_amount=int(get_setting("rate_amount", "100")),
        sleeve_multiplier=int(get_setting("sleeve_multiplier", "2")),
        customer_markup_percent=int(get_setting("customer_markup_percent", "10")),
        referral_discount_inr=int(get_setting("referral_discount_inr", "50")),
        stitching_rate=int(get_setting("stitching_rate", "500")),
        tailor_auto_order_threshold=int(get_setting("tailor_auto_order_threshold", "5")),
        tailor_auto_days_window=int(get_setting("tailor_auto_days_window", "30")),
        tailor_bulk_threshold=int(get_setting("tailor_bulk_threshold", "5")),
    )
    return render_template("admin/settings.html", form=form, upi_qr_filename=get_setting("upi_qr_filename", ""))


@bp.post("/settings")
@login_required
def settings_post():
    form = SettingsForm()
    if not form.validate_on_submit():
        return render_template("admin/settings.html", form=form, upi_qr_filename=get_setting("upi_qr_filename", "")), 400

    set_setting("business_name", form.business_name.data.strip())
    set_setting("whatsapp_number", form.whatsapp_number.data.strip())
    set_setting("email", form.email.data.strip())
    set_setting("location", form.location.data.strip())
    set_setting("upi_id", form.upi_id.data.strip())
    set_setting("stitch_threshold", str(form.stitch_threshold.data or "15000"))
    set_setting("rate_amount", str(form.rate_amount.data or "100"))
    set_setting("sleeve_multiplier", str(form.sleeve_multiplier.data or "2"))
    set_setting("customer_markup_percent", str(form.customer_markup_percent.data or "10"))
    set_setting("referral_discount_inr", str(form.referral_discount_inr.data or "50"))
    set_setting("stitching_rate", str(form.stitching_rate.data or "500"))
    set_setting("tailor_auto_order_threshold", str(form.tailor_auto_order_threshold.data or "5"))
    set_setting("tailor_auto_days_window", str(form.tailor_auto_days_window.data or "30"))
    set_setting("tailor_bulk_threshold", str(form.tailor_bulk_threshold.data or "5"))

    qr = form.upi_qr.data
    if qr:
        filename = secure_filename(qr.filename or "")
        if filename:
            ext = Path(filename).suffix.lower()
            unique = "upi_qr_" + secrets.token_hex(6) + ext
            upload_path = Path(current_app.config["UPLOAD_FOLDER"]) / unique
            qr.save(upload_path)
            set_setting("upi_qr_filename", unique)

    flash("Settings saved.", "success")
    return redirect(url_for("admin.settings"))


@bp.get("/users/new")
@login_required
def user_new():
    if current_user.role != "owner":
        flash("Only owner can create users.", "error")
        return redirect(url_for("admin.dashboard"))
    form = UserCreateForm()
    return render_template("admin/user_new.html", form=form)


@bp.post("/users/new")
@login_required
def user_new_post():
    if current_user.role != "owner":
        flash("Only owner can create users.", "error")
        return redirect(url_for("admin.dashboard"))
    form = UserCreateForm()
    if not form.validate_on_submit():
        return render_template("admin/user_new.html", form=form), 400

    email = form.email.data.strip().lower()
    if User.query.filter_by(email=email).first():
        flash("User already exists.", "error")
        return render_template("admin/user_new.html", form=form), 400

    u = User(email=email, role=form.role.data)
    u.set_password(form.password.data)
    db.session.add(u)
    db.session.commit()

    flash("User created.", "success")
    return redirect(url_for("admin.dashboard"))


# ---- Tailors ----
@bp.get("/tailors")
@login_required
def tailors_list():
    tailors = Tailor.query.order_by(Tailor.created_at.desc()).all()
    form = TailorForm()
    return render_template("admin/tailors_list.html", tailors=tailors, form=form, business_name=get_setting("business_name", "Kanna Groups"))

@bp.post("/tailors/new")
@login_required
def tailor_new():
    form = TailorForm()
    if form.validate_on_submit():
        phone = form.phone.data.strip()
        if Tailor.query.filter_by(phone=phone).first():
            flash("Tailor with this phone already exists.", "error")
        else:
            t = Tailor(name=form.name.data.strip(), phone=phone)
            db.session.add(t)
            db.session.commit()
            flash("Tailor added.", "success")
    return redirect(url_for("admin.tailors_list"))

@bp.post("/tailors/<int:tailor_id>/delete")
@login_required
def tailor_delete(tailor_id: int):
    t = Tailor.query.get_or_404(tailor_id)
    db.session.delete(t)
    db.session.commit()
    flash("Tailor removed.", "info")
    return redirect(url_for("admin.tailors_list"))


# ---- Orders ----
@bp.get("/orders")
@login_required
def orders_list():
    status_filter = request.args.get("status", "all")
    q = Order.query.order_by(Order.created_at.desc())
    if status_filter != "all":
        q = q.filter(Order.status == status_filter)
    orders = q.all()
    return render_template(
        "admin/orders_list.html",
        orders=orders,
        status_filter=status_filter,
        business_name=get_setting("business_name", "Kanna Groups"),
    )


@bp.get("/orders/<int:order_id>")
@login_required
def order_detail(order_id: int):
    order = Order.query.get_or_404(order_id)
    return render_template(
        "admin/order_detail.html",
        order=order,
        business_name=get_setting("business_name", "Kanna Groups"),
    )


@bp.post("/orders/<int:order_id>/mark-paid")
@login_required
def order_mark_paid(order_id: int):
    order = Order.query.get_or_404(order_id)
    txn_id = (request.form.get("transaction_id") or "").strip()
    if not txn_id:
        flash("Transaction ID is required to mark as paid.", "error")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    order.transaction_id = txn_id
    order.status = ORDER_STATUS_PAID
    order.admin_notes = (request.form.get("admin_notes") or "").strip() or order.admin_notes
    db.session.commit()
    flash("Order marked as Paid.", "success")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@bp.post("/orders/<int:order_id>/mark-delivered")
@login_required
def order_mark_delivered(order_id: int):
    order = Order.query.get_or_404(order_id)
    order.status = ORDER_STATUS_DELIVERED
    db.session.commit()
    flash("Order marked as Delivered.", "success")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@bp.post("/orders/<int:order_id>/mark-completed")
@login_required
def order_mark_completed(order_id: int):
    order = Order.query.get_or_404(order_id)
    order.status = ORDER_STATUS_COMPLETED
    db.session.commit()
    flash("Order marked as Completed.", "success")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@bp.post("/orders/<int:order_id>/cancel")
@login_required
def order_cancel(order_id: int):
    order = Order.query.get_or_404(order_id)
    order.status = "cancelled"
    db.session.commit()
    flash("Order cancelled.", "info")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@bp.post("/orders/<int:order_id>/delete")
@login_required
def order_delete(order_id: int):
    order = Order.query.get_or_404(order_id)
    db.session.delete(order)
    db.session.commit()
    flash("Order permanently deleted.", "success")
    return redirect(url_for("admin.orders_list"))

# ---- Custom requests ----
@bp.get("/custom-requests")
@login_required
def custom_requests_list():
    requests = CustomRequest.query.order_by(CustomRequest.created_at.desc()).all()
    return render_template(
        "admin/custom_requests_list.html",
        requests=requests,
        business_name=get_setting("business_name", "Kanna Groups"),
    )

@bp.get("/custom-requests/<int:req_id>")
@login_required
def custom_request_edit(req_id: int):
    req = CustomRequest.query.get_or_404(req_id)
    form = AdminCustomRequestEditForm(
        design_amount_inr=req.design_amount_inr,
        advance_inr=req.advance_inr,
        status=req.status
    )
    return render_template("admin/custom_request_edit.html", req=req, form=form, business_name=get_setting("business_name", "Kanna Groups"))

@bp.post("/custom-requests/<int:req_id>")
@login_required
def custom_request_edit_post(req_id: int):
    req = CustomRequest.query.get_or_404(req_id)
    form = AdminCustomRequestEditForm()
    if form.validate_on_submit():
        req.design_amount_inr = form.design_amount_inr.data
        req.advance_inr = form.advance_inr.data
        req.status = form.status.data
        # Auto-set advance_status to pending if advance amount just set and not yet paid
        if req.advance_inr and req.advance_status == "pending" and not req.advance_paid_inr:
            req.advance_status = "pending"
        db.session.commit()
        flash("Custom request updated. Customer can now pay the advance.", "success")
        return redirect(url_for("admin.custom_request_edit", req_id=req_id))
    return render_template("admin/custom_request_edit.html", req=req, form=form, business_name=get_setting("business_name", "Kanna Groups")), 400


@bp.post("/custom-requests/<int:req_id>/approve-advance")
@login_required
def custom_request_approve_advance(req_id: int):
    req = CustomRequest.query.get_or_404(req_id)
    req.advance_status = "approved"
    req.status = "in_progress"
    db.session.commit()
    flash("Advance payment approved. Work can begin.", "success")
    return redirect(url_for("admin.custom_request_edit", req_id=req_id))


@bp.post("/custom-requests/<int:req_id>/reject-advance")
@login_required
def custom_request_reject_advance(req_id: int):
    req = CustomRequest.query.get_or_404(req_id)
    req.advance_status = "pending"
    req.advance_paid_inr = None
    req.advance_transaction_id = None
    db.session.commit()
    flash("Advance payment rejected. Customer must re-submit.", "info")
    return redirect(url_for("admin.custom_request_edit", req_id=req_id))


# ---- Expenses ----
@bp.get("/expenses")
@login_required
def expenses_list():
    expenses = Expense.query.order_by(Expense.date.desc()).all()
    return render_template(
        "admin/expenses_list.html",
        expenses=expenses,
        business_name=get_setting("business_name", "Kanna Groups"),
    )


@bp.get("/expenses/new")
@login_required
def expense_new():
    form = ExpenseForm()
    return render_template(
        "admin/expense_new.html",
        form=form,
        business_name=get_setting("business_name", "Kanna Groups"),
    )


@bp.post("/expenses/new")
@login_required
def expense_new_post():
    form = ExpenseForm()
    if not form.validate_on_submit():
        return render_template(
            "admin/expense_new.html",
            form=form,
            business_name=get_setting("business_name", "Kanna Groups"),
        ), 400

    date = None
    if form.date.data:
        try:
            from datetime import datetime

            date = datetime.fromisoformat(form.date.data)
        except Exception:
            date = None

    e = Expense(
        date=date or datetime.utcnow(),
        amount_inr=form.amount_inr.data,
        category=(form.category.data or "").strip() or None,
        notes=(form.notes.data or "").strip() or None,
        expense_type=form.expense_type.data or "expense",
        vendor_name=(form.vendor_name.data or "").strip() or None,
        revenue_inr=form.revenue_inr.data or None,
        commission_inr=(
            (form.revenue_inr.data - form.amount_inr.data)
            if form.revenue_inr.data and form.amount_inr.data else None
        ),
    )
    db.session.add(e)
    db.session.commit()
    flash("Expense recorded.", "success")
    return redirect(url_for("admin.expenses_list"))


@bp.post("/expenses/<int:expense_id>/delete")
@login_required
def expense_delete(expense_id: int):
    e = Expense.query.get_or_404(expense_id)
    db.session.delete(e)
    db.session.commit()
    flash("Expense deleted.", "success")
    return redirect(url_for("admin.expenses_list"))


# ---- Reviews ----
@bp.get("/reviews")
@login_required
def reviews_list():
    reviews = Review.query.order_by(Review.created_at.desc()).all()
    return render_template(
        "admin/reviews_list.html",
        reviews=reviews,
        business_name=get_setting("business_name", "Kanna Groups"),
    )


@bp.post("/reviews/<int:review_id>/approve")
@login_required
def review_approve(review_id: int):
    r = Review.query.get_or_404(review_id)
    r.status = "approved"
    db.session.commit()
    flash("Review approved.", "success")
    return redirect(url_for("admin.reviews_list"))


@bp.post("/reviews/<int:review_id>/reject")
@login_required
def review_reject(review_id: int):
    r = Review.query.get_or_404(review_id)
    r.status = "rejected"
    db.session.commit()
    flash("Review rejected.", "info")
    return redirect(url_for("admin.reviews_list"))


@bp.post("/reviews/<int:review_id>/reply")
@login_required
def review_reply(review_id: int):
    r = Review.query.get_or_404(review_id)
    r.reply = (request.form.get("reply") or "").strip() or None
    db.session.commit()
    flash("Reply saved.", "success")
    return redirect(url_for("admin.reviews_list"))

