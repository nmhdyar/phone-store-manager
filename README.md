# Phone Store Manager

A local inventory and sales management web application built with Flask and SQLite. It provides a compact dashboard for tracking products, stock levels, sales, revenue, and gross profit.

## Features

- **Dashboard:** inventory KPIs, today's revenue, gross profit, and low-stock alerts.
- **Inventory:** create, edit, delete, search, filter, sort, sell, and restock products.
- **Sales tracking:** transaction history with revenue and gross-profit reporting.
- **Activity log:** records product, stock, sales, and settings changes.
- **Store settings:** configurable low-stock alert threshold.
- **Data integrity:** parameterized SQL, input validation, database transactions, and foreign-key enforcement.
- **Security basics:** CSRF protection, HTTP-only session cookies, and a locally generated signing key.
- **Database migration:** adds purchase-cost tracking while preserving existing product records.

## Tech stack

- Python 3.11+
- Flask 3.1
- Flask-WTF (CSRF protection)
- SQLite
- HTML and CSS

## Getting started

### 1. Create and activate a virtual environment

Run these commands in PowerShell from this directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If you have a newer supported Python version installed, you can replace `3.11` with that version.

### 2. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. Start the application

```powershell
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

If PowerShell blocks virtual-environment activation, run the environment's interpreter directly:

```powershell
.\.venv\Scripts\python.exe app.py
```

## Quality checks

Run the automated regression suite from the project directory:

```powershell
python -m compileall -q app.py database.py tests
python -m unittest discover -s tests -v
```

GitHub Actions runs the same checks on Python 3.11, 3.12, and 3.13 for pushes and pull requests to `main`.

## Project structure

```text
web_app/
├── app.py                 # Flask routes and application logic
├── database.py            # SQLite setup, migrations, and connections
├── requirements.txt       # Python dependencies
├── tests/                  # Automated regression tests
├── .github/workflows/      # Continuous integration checks
├── phone_store.db         # Created locally on first run (not committed)
├── instance/              # Local Flask signing key (not committed)
├── static/
│   └── css/style.css      # Application styles
└── templates/             # Jinja2 pages
```

## Data, configuration, and security

- The SQLite database is created locally as `phone_store.db`.
- The Flask signing key is generated in `instance/secret_key` on first run. Keep this file private and back it up securely if you need to preserve active sessions.
- You can provide a signing key through the `PHONE_STORE_SECRET_KEY` environment variable.
- Set `PHONE_STORE_HTTPS=1` when serving the app over HTTPS so session cookies use the `Secure` attribute.
- The development server binds to `127.0.0.1` and is intended for local use. The project is **not configured for public internet deployment or multi-user authentication**.
- Local databases, signing keys, virtual environments, and environment files are excluded by `.gitignore`.

## Purchase cost and profit

Purchase cost is optional when creating a product. Existing products are migrated with an **unknown** cost rather than an assumed zero cost. Revenue and stock movement are still recorded for those products, while gross profit remains unavailable until a purchase cost is entered. Each sale stores a snapshot of the unit cost used at the time of the transaction.

## Legacy data import

If the SQLite database is empty, the application can import valid product records from the older `phonestore/phones.json` file located one directory above this application. It does not merge legacy JSON records into a non-empty database.

## Backups

Stop the application before making a manual database backup, then copy `phone_store.db` to a secure location. Do not commit the database or the `instance/` directory to version control.
