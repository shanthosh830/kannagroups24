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
    image = FileField("Design image", validators=[DataRequired(), FileAllowed(["jpg", "jpeg", "png", "webp"])])


class DesignPricingForm(FlaskForm):
    is_new_arrival = SelectField("New Arrival badge", choices=[("yes", "Yes"), ("no", "No")], validators=[DataRequired()])

    # Toggles
    enable_fn = SelectField("Front Neck option", choices=[("yes", "Enabled"), ("no", "Disabled")], validators=[DataRequired()])
    enable_bn = SelectField("Back Neck option", choices=[("yes", "Enabled"), ("no", "Disabled")], validators=[DataRequired()])
    enable_sl = SelectField("Sleeve option (single sleeve ×2)", choices=[("yes", "Enabled"), ("no", "Disabled")], validators=[DataRequired()])
    enable_bn_butta = SelectField("Back Neck with Butta option", choices=[("yes", "Enabled"), ("no", "Disabled")], validators=[DataRequired()])
    enable_sl_butta = SelectField("Sleeve with Butta option (single ×2)", choices=[("yes", "Enabled"), ("no", "Disabled")], validators=[DataRequired()])

    # Stitches
    stitches_fn = IntegerField("Front Neck stitches", validators=[DataRequired()])
    stitches_bn = IntegerField("Back Neck stitches", validators=[DataRequired()])
    stitches_sl_single = IntegerField("Single Sleeve stitches", validators=[DataRequired()])
    stitches_bn_butta = IntegerField("Back Neck with Butta stitches", validators=[DataRequired()])
    stitches_sl_butta_single = IntegerField("Single Sleeve with Butta stitches", validators=[DataRequired()])

    # Design charge
    design_charge_inr = IntegerField("Design/Digitizing charge (₹) (optional)", validators=[Optional()])


class SettingsForm(FlaskForm):
    business_name = StringField("Business name", validators=[DataRequired(), Length(max=200)])
    whatsapp_number = StringField("WhatsApp number", validators=[DataRequired(), Length(max=32)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    location = StringField("Location", validators=[Optional(), Length(max=200)])
    upi_id = StringField("UPI ID", validators=[Optional(), Length(max=64)])
    upi_qr = FileField("UPI QR image (optional)", validators=[FileAllowed(["jpg", "jpeg", "png", "webp"])])


class UserCreateForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    role = SelectField("Role", choices=[("owner", "Owner"), ("digitizer", "Digitizer")], validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=255)])


class CheckoutForm(FlaskForm):
    customer_name = StringField("Name", validators=[DataRequired(), Length(max=200)])
    customer_phone = StringField("Phone / WhatsApp", validators=[DataRequired(), Length(max=32)])
    customer_email = StringField("Email (optional)", validators=[Optional(), Email(), Length(max=255)])
    address = StringField("Address", validators=[DataRequired(), Length(max=2000)])


class PaymentConfirmForm(FlaskForm):
    transaction_id = StringField("Transaction ID (optional)", validators=[Optional(), Length(max=128)])


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

