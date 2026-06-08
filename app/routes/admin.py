from __future__ import annotations

import secrets
from pathlib import Path

import cloudinary.uploader
from flask import Blueprint, Response, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename
import os

from ..extensions import db, limiter
from ..models import (
    CustomRequest,
    Design,
    DesignImage,
    DesignStitches,
    Order,
    Review,
    Service,
    User,
    get_setting,
    recompute_design_min_price,
    set_setting,
    ORDER_STATUS_PAID,
    ORDER_STATUS_PENDING_APPROVAL,
    ORDER_STATUS_PENDING_PAYMENT,
)
from ..forms import (
    AdminLoginForm,
    DesignForm,
    DesignPricingForm,
    SettingsForm,
    StitchingPricesForm,
    UserCreateForm,
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
@limiter.limit("5 per minute; 30 per hour")
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
    return render_template(
        "admin/dashboard.html",
        services=services,
        business_name=get_setting("business_name", "Kanna Groups"),
    )


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
        # Flash specific form errors so admin can see what's wrong
        for field_name, errors in form.errors.items():
            if field_name != 'csrf_token':
                for err in errors:
                    flash(f"{field_name}: {err}", "error")
        return render_template("admin/design_new.html", service=service, form=form), 400

    files = request.files.getlist("images")

    if not files or files[0].filename == "":
        flash("At least one image is required.", "error")
        return render_template("admin/design_new.html", service=service, form=form), 400

    try:
        # Create design first
        d = Design(
            service_id=service.id,
            title_en=form.title_en.data.strip(),
            title_ta=form.title_en.data.strip(),
            subcategory=form.subcategory.data.strip() if form.subcategory.data else None,
            image_filename="",  # will set later
            is_new_arrival=form.is_new_arrival.data == "yes",
            design_charge_inr=form.design_charge_inr.data,
            stitching_charge_inr=form.stitching_charge_inr.data,
        )

        db.session.add(d)
        db.session.flush()  # get ID

        # Upload all images to Cloudinary
        first_image_url = None

        for file in files:
            if not file or not file.filename:
                continue
            result = cloudinary.uploader.upload(file, folder="kannagroups/designs")
            image_url = result["secure_url"]

            if not first_image_url:
                first_image_url = image_url

            img = DesignImage(
                design_id=d.id,
                image_url=image_url
            )
            db.session.add(img)

        # Set first image as main image
        if first_image_url:
            d.image_filename = first_image_url
        else:
            flash("No images were uploaded successfully.", "error")
            db.session.rollback()
            return render_template("admin/design_new.html", service=service, form=form), 400

        # Create stitches with form data
        ds = DesignStitches(
            design_id=d.id,
            enable_fn=form.enable_fn.data == "yes",
            enable_bn=form.enable_bn.data == "yes",
            enable_sl=form.enable_sl.data == "yes",
            enable_bn_butta=form.enable_bn_butta.data == "yes",
            enable_sl_butta=form.enable_sl_butta.data == "yes",
            stitches_fn=max(0, int(form.stitches_fn.data or 0)),
            stitches_bn=max(0, int(form.stitches_bn.data or 0)),
            stitches_sl_single=max(0, int(form.stitches_sl_single.data or 0)),
            stitches_bn_butta=max(0, int(form.stitches_bn_butta.data or 0)),
            stitches_sl_butta_single=max(0, int(form.stitches_sl_butta_single.data or 0)),
        )
        db.session.add(ds)
        db.session.flush()

        recompute_design_min_price(d)
        db.session.commit()
        flash("Design uploaded successfully with pricing.", "success")
        return redirect(url_for("admin.designs_list", slug=service.slug))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Design upload failed: {e}")
        flash(f"Upload failed: {e}", "error")
        return render_template("admin/design_new.html", service=service, form=form), 500


@bp.get("/services/<slug>/designs/bulk-upload")
@login_required
def design_bulk_upload(slug: str):
    service = Service.query.filter_by(slug=slug).first_or_404()
    return render_template("admin/design_bulk_upload.html", service=service)


@bp.post("/services/<slug>/designs/bulk-upload")
@login_required
def design_bulk_upload_post(slug: str):
    service = Service.query.filter_by(slug=slug).first_or_404()

    try:
        count = int(request.form.get("design_count", 0))
    except (ValueError, TypeError):
        count = 0

    if count < 1:
        flash("No designs to upload.", "error")
        return redirect(url_for("admin.design_bulk_upload", slug=slug))

    # Collect all indices present in the form
    indices = []
    for key in request.form:
        if key.startswith("title_"):
            try:
                idx = int(key.split("_", 1)[1])
                indices.append(idx)
            except (ValueError, IndexError):
                pass
    indices.sort()

    if not indices:
        flash("No designs found in submission.", "error")
        return redirect(url_for("admin.design_bulk_upload", slug=slug))

    success_count = 0
    errors = []

    for idx in indices:
        title = (request.form.get(f"title_{idx}") or "").strip()
        if not title:
            errors.append(f"Design #{idx+1}: Title is required.")
            continue

        files = request.files.getlist(f"images_{idx}")
        if not files or not files[0].filename:
            errors.append(f"Design #{idx+1} ({title}): At least one image is required.")
            continue

        try:
            d = Design(
                service_id=service.id,
                title_en=title,
                title_ta=title,
                subcategory=request.form.get(f"subcategory_{idx}", "").strip() or None,
                image_filename="",
                is_new_arrival=request.form.get(f"is_new_arrival_{idx}") == "yes",
                design_charge_inr=_safe_int(request.form.get(f"design_charge_{idx}")),
                stitching_charge_inr=_safe_int(request.form.get(f"stitching_charge_{idx}")),
            )
            db.session.add(d)
            db.session.flush()

            first_url = None
            for f in files:
                if not f or not f.filename:
                    continue
                result = cloudinary.uploader.upload(f, folder="kannagroups/designs")
                url = result["secure_url"]
                if not first_url:
                    first_url = url
                db.session.add(DesignImage(design_id=d.id, image_url=url))

            if first_url:
                d.image_filename = first_url
            else:
                errors.append(f"Design #{idx+1} ({title}): Image upload failed.")
                db.session.rollback()
                continue

            ds = DesignStitches(
                design_id=d.id,
                enable_fn=request.form.get(f"enable_fn_{idx}") == "yes",
                enable_bn=request.form.get(f"enable_bn_{idx}") == "yes",
                enable_sl=request.form.get(f"enable_sl_{idx}") == "yes",
                enable_bn_butta=request.form.get(f"enable_bn_butta_{idx}") == "yes",
                enable_sl_butta=request.form.get(f"enable_sl_butta_{idx}") == "yes",
                stitches_fn=max(0, _safe_int(request.form.get(f"stitches_fn_{idx}"))),
                stitches_bn=max(0, _safe_int(request.form.get(f"stitches_bn_{idx}"))),
                stitches_sl_single=max(0, _safe_int(request.form.get(f"stitches_sl_{idx}"))),
                stitches_bn_butta=max(0, _safe_int(request.form.get(f"stitches_bn_butta_{idx}"))),
                stitches_sl_butta_single=max(0, _safe_int(request.form.get(f"stitches_sl_butta_{idx}"))),
            )
            db.session.add(ds)
            db.session.flush()
            recompute_design_min_price(d)
            db.session.commit()
            success_count += 1

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Bulk upload design #{idx+1} failed: {e}")
            errors.append(f"Design #{idx+1} ({title}): {e}")

    if success_count:
        flash(f"Successfully uploaded {success_count} design(s)!", "success")
    for err in errors:
        flash(err, "error")

    return redirect(url_for("admin.designs_list", slug=service.slug))


def _safe_int(val, default=0):
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        return default


@bp.get("/services/<slug>/designs")
@login_required
def designs_list(slug: str):
    service = Service.query.filter_by(slug=slug).first_or_404()
    designs = Design.query.filter_by(service_id=service.id).order_by(Design.id.desc()).all()
    return render_template("admin/designs_list.html", service=service, designs=designs)


@bp.get("/designs/<int:design_id>/edit")
@login_required
def design_details_edit(design_id: int):
    d = Design.query.get_or_404(design_id)
    # Ensure stitches row exists
    if not d.stitches:
        db.session.add(DesignStitches(design_id=d.id))
        db.session.commit()
    ds = d.stitches
    form = DesignForm(
        obj=d,
        is_new_arrival="yes" if d.is_new_arrival else "no",
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
        design_charge_inr=d.design_charge_inr,
        stitching_charge_inr=d.stitching_charge_inr,
    )
    return render_template("admin/design_edit.html", design=d, form=form, service=d.service)


@bp.post("/designs/<int:design_id>/edit")
@login_required
def design_details_edit_post(design_id: int):
    d = Design.query.get_or_404(design_id)
    title_en = request.form.get("title_en", "").strip()

    if not title_en:
        flash("Title cannot be empty.", "error")
        return redirect(url_for("admin.design_details_edit", design_id=d.id))

    # Basic fields
    d.title_en = title_en
    d.title_ta = title_en
    d.subcategory = request.form.get("subcategory", "").strip() or None
    d.is_new_arrival = request.form.get("is_new_arrival") == "yes"

    # Image
    file = request.files.get("image")
    if file and file.filename != "":
        result = cloudinary.uploader.upload(file, folder="kannagroups/designs")
        d.image_filename = result["secure_url"]
        img = DesignImage(design_id=d.id, image_url=result["secure_url"])
        db.session.add(img)

    # Charges
    d.design_charge_inr = _safe_int(request.form.get("design_charge_inr"))
    d.stitching_charge_inr = _safe_int(request.form.get("stitching_charge_inr"))

    # Stitches
    if not d.stitches:
        db.session.add(DesignStitches(design_id=d.id))
        db.session.flush()
    ds = d.stitches
    ds.enable_fn = request.form.get("enable_fn") == "yes"
    ds.enable_bn = request.form.get("enable_bn") == "yes"
    ds.enable_sl = request.form.get("enable_sl") == "yes"
    ds.enable_bn_butta = request.form.get("enable_bn_butta") == "yes"
    ds.enable_sl_butta = request.form.get("enable_sl_butta") == "yes"
    ds.stitches_fn = max(0, _safe_int(request.form.get("stitches_fn")))
    ds.stitches_bn = max(0, _safe_int(request.form.get("stitches_bn")))
    ds.stitches_sl_single = max(0, _safe_int(request.form.get("stitches_sl_single")))
    ds.stitches_bn_butta = max(0, _safe_int(request.form.get("stitches_bn_butta")))
    ds.stitches_sl_butta_single = max(0, _safe_int(request.form.get("stitches_sl_butta_single")))

    recompute_design_min_price(d)
    db.session.commit()
    flash("Design updated.", "success")
    return redirect(url_for("admin.designs_list", slug=d.service.slug))


@bp.post("/designs/<int:design_id>/delete")
@login_required
def design_delete(design_id: int):
    d = Design.query.get_or_404(design_id)
    slug = d.service.slug
    db.session.delete(d)
    db.session.commit()
    flash("Design deleted.", "success")
    return redirect(url_for("admin.designs_list", slug=slug))


@bp.get("/designs/<int:design_id>/pricing")
@login_required
def design_edit_pricing(design_id: int):
    design = Design.query.get_or_404(design_id)
    if not design.stitches:
        db.session.add(DesignStitches(design_id=design.id))
        db.session.commit()
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
        design_charge_inr=design.design_charge_inr,
        stitching_charge_inr=design.stitching_charge_inr,
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
        db.session.add(DesignStitches(design_id=design.id))
        db.session.commit()
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

    design.design_charge_inr = form.design_charge_inr.data
    design.stitching_charge_inr = form.stitching_charge_inr.data
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
    )
    return render_template("admin/settings.html", form=form, upi_qr_filename=get_setting("upi_qr_filename", ""))


@bp.post("/settings")
@login_required
def settings_post():
    form = SettingsForm()
    if not form.validate_on_submit():
        return render_template("admin/settings.html", form=form, upi_qr_filename=get_setting("upi_qr_filename", "")), 400

    # Batch all settings into one commit
    from ..models import Setting
    settings_map = {
        "business_name": form.business_name.data.strip(),
        "whatsapp_number": form.whatsapp_number.data.strip(),
        "email": form.email.data.strip(),
        "location": form.location.data.strip(),
        "upi_id": form.upi_id.data.strip(),
    }
    for key, value in settings_map.items():
        s = Setting.query.filter_by(key=key).first()
        if not s:
            db.session.add(Setting(key=key, value=value))
        else:
            s.value = value

    qr = form.upi_qr.data
    if qr:
        filename = secure_filename(qr.filename or "")
        if filename:
            result = cloudinary.uploader.upload(qr, folder="kannagroups/settings")
            qr_url = result["secure_url"]
            s = Setting.query.filter_by(key="upi_qr_filename").first()
            if not s:
                db.session.add(Setting(key="upi_qr_filename", value=qr_url))
            else:
                s.value = qr_url

    db.session.commit()
    flash("Settings saved.", "success")
    return redirect(url_for("admin.settings"))


@bp.get("/stitching-prices")
@login_required
def stitching_prices():
    form = StitchingPricesForm(
        embroidery_with_lining=get_setting("stitching_embroidery_with_lining", ""),
        embroidery_without_lining=get_setting("stitching_embroidery_without_lining", ""),
        aari_with_lining=get_setting("stitching_aari_with_lining", ""),
        aari_without_lining=get_setting("stitching_aari_without_lining", ""),
        normal_with_lining=get_setting("stitching_normal_with_lining", ""),
        normal_without_lining=get_setting("stitching_normal_without_lining", ""),
    )
    return render_template("admin/stitching_prices.html", form=form)


@bp.post("/stitching-prices")
@login_required
def stitching_prices_post():
    form = StitchingPricesForm()
    if not form.validate_on_submit():
        return render_template("admin/stitching_prices.html", form=form), 400

    from ..models import Setting
    settings_map = {
        "stitching_embroidery_with_lining": str(form.embroidery_with_lining.data or ""),
        "stitching_embroidery_without_lining": str(form.embroidery_without_lining.data or ""),
        "stitching_aari_with_lining": str(form.aari_with_lining.data or ""),
        "stitching_aari_without_lining": str(form.aari_without_lining.data or ""),
        "stitching_normal_with_lining": str(form.normal_with_lining.data or ""),
        "stitching_normal_without_lining": str(form.normal_without_lining.data or ""),
    }
    for key, value in settings_map.items():
        s = Setting.query.filter_by(key=key).first()
        if not s:
            db.session.add(Setting(key=key, value=value))
        else:
            s.value = value

    db.session.commit()
    flash("Stitching prices saved.", "success")
    return redirect(url_for("admin.stitching_prices"))


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
    if txn_id:
        order.transaction_id = txn_id
    order.status = ORDER_STATUS_PAID
    order.admin_notes = (request.form.get("admin_notes") or "").strip() or order.admin_notes
    db.session.commit()
    flash("Order marked as Paid.", "success")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@bp.post("/orders/<int:order_id>/mark-completed")
@login_required
def order_mark_completed(order_id: int):
    order = Order.query.get_or_404(order_id)
    from ..models import ORDER_STATUS_COMPLETED
    order.status = ORDER_STATUS_COMPLETED
    db.session.commit()
    flash("Order marked as Completed.", "success")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@bp.post("/orders/<int:order_id>/mark-delivered")
@login_required
def order_mark_delivered(order_id: int):
    order = Order.query.get_or_404(order_id)
    from ..models import ORDER_STATUS_DELIVERED
    order.status = ORDER_STATUS_DELIVERED
    db.session.commit()
    flash("Order marked as Delivered.", "success")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@bp.post("/orders/<int:order_id>/cancel")
@login_required
def order_cancel(order_id: int):
    order = Order.query.get_or_404(order_id)
    order.status = "cancelled"
    db.session.commit()
    flash("Order cancelled.", "info")
    return redirect(url_for("admin.order_detail", order_id=order_id))


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

