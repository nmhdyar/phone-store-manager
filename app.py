from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import os
import secrets
from pathlib import Path
import sqlite3

from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFProtect

from database import get_connection, initialize_database

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)
SECRET_FILE = INSTANCE_DIR / "secret_key"

if not SECRET_FILE.exists():
    SECRET_FILE.write_text(secrets.token_hex(32), encoding="utf-8")

app = Flask(__name__, instance_path=str(INSTANCE_DIR))
app.config.update(
    SECRET_KEY=os.environ.get("PHONE_STORE_SECRET_KEY") or SECRET_FILE.read_text(encoding="utf-8").strip(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("PHONE_STORE_HTTPS", "0") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
)
CSRFProtect(app)

MAX_MONEY = Decimal("999999999999.99")
MAX_QUANTITY = 2_147_483_647


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
        "form-action 'self'; img-src 'self' data:; style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com",
    )
    return response
initialize_database()


def parse_money(value, *, allow_zero=False):
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        raise ValueError("Enter a valid amount.")
    if not amount.is_finite() or amount < 0 or (not allow_zero and amount == 0):
        raise ValueError("Amount must be a finite positive number.")
    try:
        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError("Amount is outside the supported range.")
    if amount > MAX_MONEY:
        raise ValueError("Amount exceeds the supported limit.")
    return float(amount)


def parse_quantity(value, *, allow_zero=True):
    try:
        number = int(str(value).strip())
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Quantity must be a whole number.")
    if number < 0 or (not allow_zero and number == 0) or number > MAX_QUANTITY:
        raise ValueError("Quantity is outside the allowed range.")
    return number


def get_setting(connection, key, default):
    row = connection.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else str(default)


def log_activity(connection, action, details):
    connection.execute(
        "INSERT INTO activity_log(action, details) VALUES (?, ?)",
        (action, details),
    )


def fetch_phone(phone_id):
    with get_connection() as connection:
        phone = connection.execute("SELECT * FROM phones WHERE id = ?", (phone_id,)).fetchone()
    if phone is None:
        abort(404)
    return phone


@app.context_processor
def inject_globals():
    with get_connection() as connection:
        threshold = int(get_setting(connection, "low_stock_limit", 5))
    return {"low_stock_limit": threshold}


@app.route("/")
def dashboard():
    with get_connection() as connection:
        threshold = int(get_setting(connection, "low_stock_limit", 5))
        stats = connection.execute("""
            SELECT COUNT(*) AS total_products,
                   COALESCE(SUM(quantity), 0) AS total_stock,
                   COALESCE(SUM(price * quantity), 0) AS inventory_value,
                   COALESCE(SUM(CASE WHEN quantity <= ? THEN 1 ELSE 0 END), 0) AS low_stock
            FROM phones
        """, (threshold,)).fetchone()
        low_stock_phones = connection.execute(
            "SELECT id, name, quantity FROM phones WHERE quantity <= ? ORDER BY quantity, name",
            (threshold,),
        ).fetchall()
        search = request.args.get("q", "").strip()[:100]
        stock_filter = request.args.get("stock", "all")
        sort_key = request.args.get("sort", "newest")
        sort_options = {
            "newest": "id DESC",
            "name": "name COLLATE NOCASE ASC",
            "price_high": "price DESC",
            "price_low": "price ASC",
            "quantity": "quantity ASC",
            "value": "(price * quantity) DESC",
        }
        where_parts = []
        params = []
        if search:
            where_parts.append("name LIKE ?")
            params.append(f"%{search}%")
        if stock_filter == "low":
            where_parts.append("quantity <= ?")
            params.append(threshold)
        elif stock_filter == "available":
            where_parts.append("quantity > ?")
            params.append(threshold)
        where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
        order_sql = sort_options.get(sort_key, sort_options["newest"])
        phones = connection.execute(
            f"SELECT * FROM phones{where_sql} ORDER BY {order_sql} LIMIT 250",
            params,
        ).fetchall()
        recent_sales = connection.execute("SELECT * FROM sales ORDER BY id DESC LIMIT 5").fetchall()
        recent_activity = connection.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT 6").fetchall()
        sales_today = connection.execute(
            "SELECT COALESCE(SUM(total),0) AS revenue, COALESCE(SUM(profit),0) AS profit, COUNT(*) AS count "
            "FROM sales WHERE date(created_at) = date('now','localtime')"
        ).fetchone()
    return render_template(
        "index.html", stats=stats, low_stock_phones=low_stock_phones,
        phones=phones, recent_sales=recent_sales, recent_activity=recent_activity,
        sales_today=sales_today, threshold=threshold,
        search=search, stock_filter=stock_filter, sort_key=sort_key,
    )


@app.route("/add", methods=["GET", "POST"])
def add_phone():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        try:
            price = parse_money(request.form.get("price"))
            raw_cost = request.form.get("cost_price", "").strip()
            cost_price = parse_money(raw_cost, allow_zero=True) if raw_cost else None
            quantity = parse_quantity(request.form.get("quantity"))
            if not name or len(name) > 120:
                raise ValueError("Name is required and must be no longer than 120 characters.")
            with get_connection() as connection:
                connection.execute(
                    "INSERT INTO phones(name, price, cost_price, cost_known, quantity) VALUES (?, ?, ?, ?, ?)",
                    (name, price, cost_price or 0, int(cost_price is not None), quantity),
                )
                log_activity(connection, "Product added", f"{name} added with {quantity} units.")
            flash("Product added successfully.", "success")
            return redirect(url_for("dashboard"))
        except ValueError as exc:
            flash(str(exc), "error")
        except sqlite3.IntegrityError:
            flash("A product with this name already exists.", "error")
    return render_template("add_phone.html")


@app.route("/edit/<int:phone_id>", methods=["GET", "POST"])
def edit_phone(phone_id):
    phone = fetch_phone(phone_id)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        try:
            price = parse_money(request.form.get("price"))
            raw_cost = request.form.get("cost_price", "").strip()
            cost_price = parse_money(raw_cost, allow_zero=True) if raw_cost else None
            quantity = parse_quantity(request.form.get("quantity"))
            if not name or len(name) > 120:
                raise ValueError("Name is required and must be no longer than 120 characters.")
            with get_connection() as connection:
                if cost_price is None:
                    connection.execute(
                        "UPDATE phones SET name=?, price=?, quantity=? WHERE id=?",
                        (name, price, quantity, phone_id),
                    )
                else:
                    connection.execute(
                        "UPDATE phones SET name=?, price=?, cost_price=?, cost_known=1, quantity=? WHERE id=?",
                        (name, price, cost_price, quantity, phone_id),
                    )
                log_activity(connection, "Product updated", f"{name} details were updated.")
            flash("Product updated successfully.", "success")
            return redirect(url_for("dashboard"))
        except ValueError as exc:
            flash(str(exc), "error")
        except sqlite3.IntegrityError:
            flash("Another product already uses this name.", "error")
    return render_template("edit_phone.html", phone=phone)


@app.route("/delete/<int:phone_id>", methods=["GET", "POST"])
def delete_phone(phone_id):
    phone = fetch_phone(phone_id)
    if request.method == "POST":
        with get_connection() as connection:
            connection.execute("DELETE FROM phones WHERE id = ?", (phone_id,))
            log_activity(connection, "Product deleted", f"{phone['name']} was removed from inventory.")
        flash("Product deleted. Historical sales were preserved.", "success")
        return redirect(url_for("dashboard"))
    return render_template("delete_phone.html", phone=phone)


@app.route("/sell/<int:phone_id>", methods=["GET", "POST"])
def sell_phone(phone_id):
    phone = fetch_phone(phone_id)
    if request.method == "POST":
        try:
            quantity = parse_quantity(request.form.get("quantity"), allow_zero=False)
            unit_price = parse_money(request.form.get("unit_price"))
            with get_connection() as connection:
                # Acquire the write lock with a conditional update before reading the
                # cost snapshot. This prevents two simultaneous sales overselling stock.
                update = connection.execute(
                    "UPDATE phones SET quantity=quantity-? WHERE id=? AND quantity>=?",
                    (quantity, phone_id, quantity),
                )
                if update.rowcount != 1:
                    available = connection.execute(
                        "SELECT quantity FROM phones WHERE id=?", (phone_id,)
                    ).fetchone()
                    if available is None:
                        abort(404)
                    raise ValueError(f"Only {available['quantity']} units are available.")
                current = connection.execute(
                    "SELECT name, cost_price, cost_known FROM phones WHERE id=?",
                    (phone_id,),
                ).fetchone()
                total = float((Decimal(str(unit_price)) * quantity).quantize(Decimal("0.01")))
                profit = (
                    float(((Decimal(str(unit_price)) - Decimal(str(current["cost_price"]))) * quantity).quantize(Decimal("0.01")))
                    if current["cost_known"] else None
                )
                connection.execute(
                    "INSERT INTO sales(phone_id, phone_name, quantity, unit_price, unit_cost, total, profit) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (phone_id, current["name"], quantity, unit_price, current["cost_price"], total, profit),
                )
                log_activity(connection, "Sale completed", f"{quantity} × {current['name']} · {total:,.0f} Toman.")
            flash("Sale recorded and inventory updated.", "success")
            return redirect(url_for("sales"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("sell_phone.html", phone=phone)


@app.route("/restock/<int:phone_id>", methods=["GET", "POST"])
def restock_phone(phone_id):
    phone = fetch_phone(phone_id)
    if request.method == "POST":
        try:
            quantity = parse_quantity(request.form.get("quantity"), allow_zero=False)
            with get_connection() as connection:
                update = connection.execute(
                    "UPDATE phones SET quantity=quantity+? WHERE id=? AND quantity<=?",
                    (quantity, phone_id, MAX_QUANTITY - quantity),
                )
                if update.rowcount != 1:
                    current = connection.execute(
                        "SELECT quantity FROM phones WHERE id=?", (phone_id,)
                    ).fetchone()
                    if current is None:
                        abort(404)
                    raise ValueError("The resulting stock quantity would exceed the supported limit.")
                log_activity(connection, "Stock replenished", f"{quantity} units added to {phone['name']}.")
            flash("Inventory restocked.", "success")
            return redirect(url_for("dashboard"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("restock_phone.html", phone=phone)


@app.route("/sales")
def sales():
    search = request.args.get("q", "").strip()[:100]
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM sales WHERE phone_name LIKE ? ORDER BY id DESC LIMIT 250",
            (f"%{search}%",),
        ).fetchall()
        totals = connection.execute(
            "SELECT COUNT(*) AS transactions, COALESCE(SUM(total),0) AS revenue, "
            "COALESCE(SUM(profit),0) AS profit, "
            "SUM(CASE WHEN profit IS NOT NULL THEN 1 ELSE 0 END) AS known_cost_transactions "
            "FROM sales"
        ).fetchone()
    return render_template("sales.html", sales=rows, totals=totals, search=search)


@app.route("/activity")
def activity():
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT 300").fetchall()
    return render_template("activity.html", activities=rows)


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        try:
            threshold = parse_quantity(request.form.get("low_stock_limit"))
            if threshold > 100000:
                raise ValueError("Low-stock threshold is too large.")
            with get_connection() as connection:
                connection.execute(
                    "INSERT INTO app_settings(key,value) VALUES('low_stock_limit',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(threshold),),
                )
                log_activity(connection, "Settings updated", f"Low-stock alert threshold set to {threshold}.")
            flash("Settings saved.", "success")
            return redirect(url_for("settings"))
        except ValueError as exc:
            flash(str(exc), "error")
    with get_connection() as connection:
        threshold = int(get_setting(connection, "low_stock_limit", 5))
    return render_template("settings.html", threshold=threshold)


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="The page or product could not be found."), 404


@app.errorhandler(500)
def server_error(_error):
    return render_template("error.html", code=500, message="Something went wrong. Please try again."), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
