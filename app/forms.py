from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import IntegerField, PasswordField, SelectField, StringField
from wtforms.validators import DataRequired, Email, Length, Optional
from flask_wtf.file import FileAllowed, FileField


class AdminLoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=255)])


class DesignForm(FlaskForm):
    title_en = StringField("Title (English)", validators=[DataRequired(), Length(max=200)])
    title_ta = StringField("Title (Tamil)", validators=[DataRequired(), Length(max=200)])
    subcategory = SelectField(
        "Subcategory",
        choices=[
            ("", "(None)"),
            ("chudi", "Chudi"),
            ("blouse", "Blouse"),
            ("bridal_blouse", "Bridal Blouse"),
            ("other", "Other"),
        ],
        validators=[Optional()],
    )
    image = FileField("Design image", validators=[DataRequired(), FileAllowed(["jpg", "jpeg", "png", "webp"])])


class DesignEditForm(FlaskForm):
    title_en = StringField("Title (English)", validators=[DataRequired(), Length(max=200)])
    title_ta = StringField("Title (Tamil)", validators=[DataRequired(), Length(max=200)])
    subcategory = SelectField(
        "Subcategory",
        choices=[
            ("", "(None)"),
            ("chudi", "Chudi"),
            ("blouse", "Blouse"),
            ("bridal_blouse", "Bridal Blouse"),
            ("other", "Other"),
        ],
        validators=[Optional()],
    )
    image = FileField("Design image", validators=[Optional(), FileAllowed(["jpg", "jpeg", "png", "webp"])])


class DesignPricingForm(FlaskForm):
    is_new_arrival = SelectField("New Arrival badge", choices=[("yes", "Yes"), ("no", "No")], validators=[DataRequired()])

    # Toggles
    enable_fn = SelectField("Front Neck option", choices=[("yes", "Enabled"), ("no", "Disabled")], validators=[DataRequired()])
    enable_bn = SelectField("Back Neck option", choices=[("yes", "Enabled"), ("no", "Disabled")], validators=[DataRequired()])
    enable_sl = SelectField("Sleeve option (single sleeve ×2)", choices=[("yes", "Enabled"), ("no", "Disabled")], validators=[DataRequired()])
    enable_bn_butta = SelectField("Back Neck with Butta option", choices=[("yes", "Enabled"), ("no", "Disabled")], validators=[DataRequired()])
    enable_sl_butta = SelectField("Sleeve with Butta option (single ×2)", choices=[("yes", "Enabled"), ("no", "Disabled")], validators=[DataRequired()])

    # Stitches
    stitches_fn = IntegerField("Front Neck stitches", validators=[Optional()])
    stitches_bn = IntegerField("Back Neck stitches", validators=[Optional()])
    stitches_sl_single = IntegerField("Single Sleeve stitches", validators=[Optional()])
    stitches_bn_butta = IntegerField("Back Neck with Butta stitches", validators=[Optional()])
    stitches_sl_butta_single = IntegerField("Single Sleeve with Butta stitches", validators=[Optional()])

    # Per-area prices (₹) — these add up based on customer selection
    price_fn = IntegerField("Front Neck price (₹)", validators=[Optional()])
    price_bn = IntegerField("Back Neck price (₹)", validators=[Optional()])
    price_sl = IntegerField("Sleeve price (₹)", validators=[Optional()])
    price_bn_butta = IntegerField("Back Neck with Butta price (₹)", validators=[Optional()])
    price_sl_butta = IntegerField("Sleeve with Butta price (₹)", validators=[Optional()])

    # Manual pricing (overrides everything)
    manual_price_inr = IntegerField("Manual fixed price (₹) — overrides all above", validators=[Optional()])

    # Design charge
    design_charge_inr = IntegerField("Design/Digitizing charge (₹) (optional)", validators=[Optional()])


class SettingsForm(FlaskForm):
    business_name = StringField("Business name", validators=[DataRequired(), Length(max=200)])
    whatsapp_number = StringField("WhatsApp number", validators=[DataRequired(), Length(max=32)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    location = StringField("Location", validators=[Optional(), Length(max=200)])
    upi_id = StringField("UPI ID", validators=[Optional(), Length(max=64)])
    upi_qr = FileField("UPI QR image (optional)", validators=[FileAllowed(["jpg", "jpeg", "png", "webp"])])

    # Stitch pricing settings
    stitch_threshold = IntegerField("Stitch threshold", validators=[Optional()])
    rate_amount = IntegerField("Rate amount (₹)", validators=[Optional()])
    sleeve_multiplier = IntegerField("Sleeve multiplier", validators=[Optional()])
    customer_markup_percent = IntegerField("Customer markup (%)", validators=[Optional()])
    referral_discount_inr = IntegerField("Referral discount (₹)", validators=[Optional()])
    stitching_rate = IntegerField("Stitching rate (₹)", validators=[Optional()])

    # Tailor auto-detection thresholds
    tailor_auto_order_threshold = IntegerField("Auto-tailor: min orders in period", validators=[Optional()])
    tailor_auto_days_window = IntegerField("Auto-tailor: days window", validators=[Optional()])
    tailor_bulk_threshold = IntegerField("Auto-tailor: bulk cart items", validators=[Optional()])


class UserCreateForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    role = SelectField("Role", choices=[("owner", "Owner"), ("digitizer", "Digitizer")], validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=255)])


class CheckoutForm(FlaskForm):
    customer_name = StringField("Name", validators=[DataRequired(), Length(max=200)])
    customer_phone = StringField("Phone / WhatsApp", validators=[DataRequired(), Length(max=32)])
    customer_email = StringField("Email (optional)", validators=[Optional(), Email(), Length(max=255)])
    address = StringField("Address", validators=[DataRequired(), Length(max=2000)])
    referral_code = StringField("Referral code (optional)", validators=[Optional(), Length(max=64)])


class PaymentConfirmForm(FlaskForm):
    transaction_id = StringField("Transaction ID", validators=[DataRequired(), Length(max=128)])


class ReviewForm(FlaskForm):
    customer_name = StringField("Your name", validators=[DataRequired(), Length(max=200)])
    order_code = StringField("Order code (optional)", validators=[Optional(), Length(max=64)])
    rating = IntegerField("Rating (1-5)", validators=[DataRequired()])
    text = StringField("Your review", validators=[DataRequired(), Length(max=2000)])


class CustomDesignForm(FlaskForm):
    customer_name = StringField("Your name", validators=[DataRequired(), Length(max=200)])
    customer_phone = StringField("Phone / WhatsApp", validators=[DataRequired(), Length(max=32)])
    description = StringField("Design description", validators=[DataRequired(), Length(max=2000)])
    areas = StringField("Areas (fn,bn,sl etc)")  # we'll use checkboxes in template and join
    payment_method = SelectField("Payment", choices=[("upi", "UPI"), ("cash", "Cash")], validators=[Optional()])
    notes = StringField("Additional notes", validators=[Optional(), Length(max=500)])
    image = FileField("Design image (optional)", validators=[FileAllowed(["jpg", "jpeg", "png", "webp"])])


class ExpenseForm(FlaskForm):
    date = StringField("Date (YYYY-MM-DD)", validators=[Optional(), Length(max=20)])
    amount_inr = IntegerField("Amount paid out (₹)", validators=[DataRequired()])
    category = StringField("Category (e.g. Thread, Stitching, Aari)", validators=[Optional(), Length(max=100)])
    notes = StringField("Notes", validators=[Optional(), Length(max=500)])
    expense_type = SelectField("Type", choices=[("expense", "Expense"), ("commission", "Commission Work")], validators=[DataRequired()])
    vendor_name = StringField("Vendor / Worker name", validators=[Optional(), Length(max=200)])
    revenue_inr = IntegerField("Amount charged to customer (₹)", validators=[Optional()])


class CustomRequestAdvanceForm(FlaskForm):
    transaction_id = StringField("Transaction ID", validators=[DataRequired(), Length(max=128)])


class TailorForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=200)])
    phone = StringField("Phone / WhatsApp", validators=[DataRequired(), Length(max=32)])


class AdminCustomRequestEditForm(FlaskForm):
    design_amount_inr = IntegerField("Designing Amount (₹)", validators=[Optional()])
    advance_inr = IntegerField("Advance Required (₹)", validators=[Optional()])
    status = SelectField("Status", choices=[("pending", "Pending"), ("in_progress", "In Progress"), ("completed", "Completed"), ("cancelled", "Cancelled")], validators=[DataRequired()])
