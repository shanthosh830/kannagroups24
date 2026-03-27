# Kanna Groups (Option A) — Flask Website + Admin Uploads

This is a ready-to-use Flask website for **Kanna Groups**:

- Public: Services → Designs grid → **Design detail with zoom + price**
- Admin: Login → Upload designs under each service → Set price (shown only on detail page)
- WhatsApp button: customers can enquire/order via WhatsApp

## Run locally (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

Open:
- Public site: `http://127.0.0.1:5000/`
- First-time owner setup: `http://127.0.0.1:5000/admin/bootstrap`
- Admin login: `http://127.0.0.1:5000/admin/login`

## Uploads

Uploaded images are stored in `instance/uploads/` (local dev).

