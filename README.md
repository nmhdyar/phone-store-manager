# Phone Store Manager

A local Flask + SQLite inventory and sales manager.

## Features

- Dashboard with inventory KPIs, today's revenue, and low-stock alerts
- Product create, edit, delete, search, and stock management
- Sales transactions that atomically decrement inventory
- Sales history with revenue and gross-profit reporting
- Activity log for product, stock, sales, and settings changes
- Configurable low-stock threshold
- Input validation, parameterized SQL, CSRF protection, and safe local defaults
- Database migration adds purchase-cost tracking without deleting existing products

## Requirements

- Windows 10/11
- Python 3.11 or newer

## Setup (PowerShell)

From this folder:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

If PowerShell blocks environment activation, run the interpreter directly:

```powershell
.\.venv\Scripts\python.exe app.py
```

## Data and backups

- SQLite data is stored in `phone_store.db`.
- Flask's signing key is generated in `instance\secret_key`; keep it private and do not delete it while sessions are in use.
- Before making manual database changes, stop the app and copy `phone_store.db`.
- The app binds to `127.0.0.1` by default. It is not configured for public internet deployment or multi-user authentication.

## Purchase cost and profit

Purchase cost is optional when adding a product. Existing products are migrated with an **unknown** cost, not a fabricated zero cost. Sales for those products still record revenue and stock movement, but profit is marked unavailable until a purchase cost is entered on the Edit Product page. Historical sales retain the cost snapshot used at the time of sale.

## Legacy JSON

When the SQLite database is empty, the app can import valid records from the older `phonestore\phones.json` file. It does not merge that file into a non-empty database.
