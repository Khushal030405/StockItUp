from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify, Response
import sqlite3
from datetime import datetime, date, timedelta
from functools import wraps
import csv
import io
import os
import json
from werkzeug.security import generate_password_hash, check_password_hash

APP_NAME = "StockItUp"
DB_PATH = "stockitup.db"

app = Flask(__name__)
app.secret_key = "stockitup_pro_secret_change_me"


def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def execute(query, params=(), fetchone=False, fetchall=False, commit=False):
    conn = db()
    cur = conn.cursor()
    cur.execute(query, params)
    result = None
    if fetchone:
        result = cur.fetchone()
    if fetchall:
        result = cur.fetchall()
    if commit:
        conn.commit()
    conn.close()
    return result


def init_db():
    conn = db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('master','admin','employee')),
        branch TEXT DEFAULT 'Main Branch',
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        barcode TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        brand TEXT DEFAULT '',
        cost_price REAL DEFAULT 0,
        selling_price REAL NOT NULL,
        quantity INTEGER NOT NULL,
        low_stock_limit INTEGER DEFAULT 5,
        expiry_date TEXT DEFAULT '',
        branch TEXT DEFAULT 'Main Branch',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS customers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT DEFAULT '',
        email TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_no TEXT UNIQUE NOT NULL,
        customer_id INTEGER,
        customer_name TEXT DEFAULT 'Walk-in Customer',
        subtotal REAL DEFAULT 0,
        discount REAL DEFAULT 0,
        total REAL DEFAULT 0,
        profit REAL DEFAULT 0,
        payment_mode TEXT DEFAULT 'Cash',
        sold_by TEXT,
        branch TEXT DEFAULT 'Main Branch',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS order_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        barcode TEXT NOT NULL,
        category TEXT,
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        cost_price REAL DEFAULT 0,
        subtotal REAL NOT NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS attendance(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        status TEXT NOT NULL,
        branch TEXT DEFAULT 'Main Branch',
        marked_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS branches(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        location TEXT DEFAULT '',
        active INTEGER DEFAULT 1
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS activity_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        action TEXT,
        details TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()

    def add_user(name, username, password, role, branch="Main Branch"):
        c.execute("SELECT id FROM users WHERE username=?", (username,))
        if not c.fetchone():
            c.execute("""
                INSERT INTO users(name, username, password_hash, role, branch)
                VALUES(?,?,?,?,?)
            """, (name, username, generate_password_hash(password), role, branch))

    add_user("Master Admin", "masteradmin", "admin123", "master")
    add_user("Branch Admin", "admin", "admin123", "admin")
    add_user("Employee", "employee", "emp123", "employee")

    c.execute("INSERT OR IGNORE INTO branches(name, location) VALUES('Main Branch','Default Location')")

    sample_products = [
        ("8901000000011", "Premium Notebook", "Stationery", "Classmate", 35, 60, 25, 5, ""),
        ("8901000000028", "Blue Ball Pen", "Stationery", "Cello", 5, 10, 80, 10, ""),
        ("8901000000035", "Wireless Mouse", "Electronics", "LogiTech", 320, 499, 12, 4, ""),
        ("8901000000042", "USB Cable Type-C", "Electronics", "StockItUp", 70, 149, 3, 5, ""),
        ("8901000000059", "Cold Coffee", "Beverages", "Cafe", 20, 50, 18, 8, (date.today()+timedelta(days=5)).isoformat()),
    ]

    for p in sample_products:
        c.execute("SELECT id FROM products WHERE barcode=?", (p[0],))
        if not c.fetchone():
            c.execute("""
                INSERT INTO products(barcode,name,category,brand,cost_price,selling_price,quantity,low_stock_limit,expiry_date)
                VALUES(?,?,?,?,?,?,?,?,?)
            """, p)

    conn.commit()
    conn.close()


def log(action, details=""):
    try:
        execute(
            "INSERT INTO activity_logs(username, action, details) VALUES(?,?,?)",
            (session.get("username", "system"), action, details),
            commit=True
        )
    except Exception:
        pass


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def roles_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                flash("You do not have permission to access that page.", "danger")
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)
        return wrapper
    return decorator


@app.context_processor
def inject_globals():
    return {
        "app_name": APP_NAME,
        "current_user": session.get("name"),
        "current_role": session.get("role"),
        "currency": "₹",
        "today": date.today().strftime("%d %b %Y")
    }


@app.route("/")
def index():
    return render_template("splash.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = execute("SELECT * FROM users WHERE username=? AND active=1", (username,), fetchone=True)

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            session["branch"] = user["branch"]
            log("LOGIN", "User logged in")
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    log("LOGOUT", "User logged out")
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    product_count = execute("SELECT COUNT(*) c FROM products", fetchone=True)["c"]
    low_stock = execute("SELECT COUNT(*) c FROM products WHERE quantity <= low_stock_limit", fetchone=True)["c"]
    expiry_soon = execute("""
        SELECT COUNT(*) c FROM products 
        WHERE expiry_date!='' AND date(expiry_date) <= date('now','+7 day')
    """, fetchone=True)["c"]
    today_sales = execute("""
        SELECT COALESCE(SUM(total),0) total FROM orders WHERE date(created_at)=date('now')
    """, fetchone=True)["total"]
    today_profit = execute("""
        SELECT COALESCE(SUM(profit),0) profit FROM orders WHERE date(created_at)=date('now')
    """, fetchone=True)["profit"]
    employees_present = execute("""
        SELECT COUNT(DISTINCT username) c FROM attendance WHERE date(marked_at)=date('now') AND status='Present'
    """, fetchone=True)["c"]
    recent_orders = execute("SELECT * FROM orders ORDER BY id DESC LIMIT 6", fetchall=True)

    daily = execute("""
        SELECT date(created_at) d, COALESCE(SUM(total),0) total
        FROM orders
        WHERE date(created_at) >= date('now','-6 day')
        GROUP BY date(created_at)
        ORDER BY d
    """, fetchall=True)

    top_products = execute("""
        SELECT product_name, SUM(quantity) qty
        FROM order_items
        GROUP BY product_name
        ORDER BY qty DESC
        LIMIT 5
    """, fetchall=True)

    ai_note = "Sales look stable. Keep monitoring low-stock items."
    if low_stock > 0:
        ai_note = f"{low_stock} products need restocking soon. Prioritize fast-moving items."
    if today_sales > 0 and today_profit <= 0:
        ai_note = "Revenue is recorded today, but profit is low. Recheck cost prices."

    return render_template(
        "dashboard.html",
        product_count=product_count,
        low_stock=low_stock,
        expiry_soon=expiry_soon,
        today_sales=today_sales,
        today_profit=today_profit,
        employees_present=employees_present,
        recent_orders=recent_orders,
        daily=daily,
        top_products=top_products,
        ai_note=ai_note
    )


@app.route("/inventory")
@login_required
def inventory():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    sql = "SELECT * FROM products WHERE 1=1"
    params = []

    if q:
        sql += " AND (name LIKE ? OR barcode LIKE ? OR brand LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]

    if category:
        sql += " AND category=?"
        params.append(category)

    sql += " ORDER BY id DESC"
    products = execute(sql, params, fetchall=True)
    categories = execute("SELECT DISTINCT category FROM products ORDER BY category", fetchall=True)

    return render_template("inventory.html", products=products, categories=categories, q=q, selected_category=category)


@app.route("/inventory/add", methods=["GET", "POST"])
@login_required
def add_product():
    if request.method == "POST":
        try:
            execute("""
                INSERT INTO products(barcode,name,category,brand,cost_price,selling_price,quantity,low_stock_limit,expiry_date,branch)
                VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (
                request.form["barcode"].strip(),
                request.form["name"].strip(),
                request.form["category"].strip(),
                request.form.get("brand","").strip(),
                float(request.form.get("cost_price") or 0),
                float(request.form["selling_price"]),
                int(request.form["quantity"]),
                int(request.form.get("low_stock_limit") or 5),
                request.form.get("expiry_date",""),
                session.get("branch","Main Branch")
            ), commit=True)
            log("ADD_PRODUCT", request.form["name"])
            flash("Product added successfully.", "success")
            return redirect(url_for("inventory"))
        except sqlite3.IntegrityError:
            flash("Barcode already exists.", "danger")
        except Exception as e:
            flash(f"Could not add product: {e}", "danger")

    return render_template("product_form.html", product=None)


@app.route("/inventory/edit/<int:product_id>", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    product = execute("SELECT * FROM products WHERE id=?", (product_id,), fetchone=True)

    if not product:
        flash("Product not found.", "danger")
        return redirect(url_for("inventory"))

    if request.method == "POST":
        execute("""
            UPDATE products SET barcode=?, name=?, category=?, brand=?, cost_price=?, selling_price=?,
            quantity=?, low_stock_limit=?, expiry_date=? WHERE id=?
        """, (
            request.form["barcode"].strip(),
            request.form["name"].strip(),
            request.form["category"].strip(),
            request.form.get("brand","").strip(),
            float(request.form.get("cost_price") or 0),
            float(request.form["selling_price"]),
            int(request.form["quantity"]),
            int(request.form.get("low_stock_limit") or 5),
            request.form.get("expiry_date",""),
            product_id
        ), commit=True)
        log("EDIT_PRODUCT", request.form["name"])
        flash("Product updated.", "success")
        return redirect(url_for("inventory"))

    return render_template("product_form.html", product=product)


@app.route("/inventory/delete/<int:product_id>", methods=["POST"])
@roles_required("master", "admin")
def delete_product(product_id):
    execute("DELETE FROM products WHERE id=?", (product_id,), commit=True)
    log("DELETE_PRODUCT", f"Product ID {product_id}")
    flash("Product deleted.", "success")
    return redirect(url_for("inventory"))


@app.route("/scanner")
@login_required
def scanner():
    return render_template("scanner.html")


@app.route("/api/product/<barcode>")
@login_required
def api_product(barcode):
    p = execute("SELECT * FROM products WHERE barcode=?", (barcode,), fetchone=True)

    if not p:
        return jsonify({"ok": False, "message": "Product not found"})

    return jsonify({"ok": True, "product": dict(p)})


@app.route("/billing", methods=["GET", "POST"])
@login_required
def billing():
    if request.method == "POST":
        raw_items = request.form.get("items_json", "[]")

        try:
            items = json.loads(raw_items) if raw_items else []
        except Exception:
            flash("Invalid cart data. Please add products to the cart again.", "danger")
            return redirect(url_for("billing"))

        if not isinstance(items, list) or not items:
            flash("Cart is empty. Please add at least one product before generating bill.", "danger")
            return redirect(url_for("billing"))

        customer_name = request.form.get("customer_name","Walk-in Customer").strip() or "Walk-in Customer"
        customer_phone = request.form.get("customer_phone","").strip()
        payment_mode = request.form.get("payment_mode","Cash")
        discount = float(request.form.get("discount") or 0)

        conn = db()
        c = conn.cursor()
        subtotal = 0
        profit = 0
        checked_items = []

        try:
            for item in items:
                barcode = str(item["barcode"]).strip()
                qty = int(item["qty"])

                if qty <= 0:
                    raise Exception("Quantity must be positive.")

                c.execute("SELECT * FROM products WHERE barcode=?", (barcode,))
                p = c.fetchone()

                if not p:
                    raise Exception(f"Product not found: {barcode}")

                if p["quantity"] < qty:
                    raise Exception(f"Not enough stock for {p['name']}. Available: {p['quantity']}")

                line_total = qty * float(p["selling_price"])
                line_profit = qty * (float(p["selling_price"]) - float(p["cost_price"]))
                subtotal += line_total
                profit += line_profit
                checked_items.append((p, qty, line_total))

            total = max(subtotal - discount, 0)
            invoice_no = "INV" + datetime.now().strftime("%Y%m%d%H%M%S")

            customer_id = None

            if customer_phone:
                c.execute("SELECT id FROM customers WHERE phone=?", (customer_phone,))
                existing = c.fetchone()

                if existing:
                    customer_id = existing["id"]
                else:
                    c.execute("INSERT INTO customers(name, phone) VALUES(?,?)", (customer_name, customer_phone))
                    customer_id = c.lastrowid

            c.execute("""
                INSERT INTO orders(invoice_no, customer_id, customer_name, subtotal, discount, total, profit, payment_mode, sold_by, branch)
                VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (
                invoice_no,
                customer_id,
                customer_name,
                subtotal,
                discount,
                total,
                profit,
                payment_mode,
                session["username"],
                session.get("branch","Main Branch")
            ))

            order_id = c.lastrowid

            for p, qty, line_total in checked_items:
                c.execute("""
                    INSERT INTO order_items(order_id,product_id,product_name,barcode,category,quantity,price,cost_price,subtotal)
                    VALUES(?,?,?,?,?,?,?,?,?)
                """, (
                    order_id,
                    p["id"],
                    p["name"],
                    p["barcode"],
                    p["category"],
                    qty,
                    p["selling_price"],
                    p["cost_price"],
                    line_total
                ))

                c.execute("UPDATE products SET quantity = quantity - ? WHERE id=?", (qty, p["id"]))

            conn.commit()
            log("SALE", invoice_no)
            flash("Bill generated successfully.", "success")
            return redirect(url_for("invoice", order_id=order_id))

        except Exception as e:
            conn.rollback()
            flash(str(e), "danger")
            return redirect(url_for("billing"))

        finally:
            conn.close()

    products = execute("SELECT * FROM products WHERE quantity > 0 ORDER BY name", fetchall=True)
    return render_template("billing.html", products=products)


@app.route("/invoice/<int:order_id>")
@login_required
def invoice(order_id):
    order = execute("SELECT * FROM orders WHERE id=?", (order_id,), fetchone=True)
    items = execute("SELECT * FROM order_items WHERE order_id=?", (order_id,), fetchall=True)

    if not order:
        flash("Invoice not found.", "danger")
        return redirect(url_for("billing"))

    return render_template("invoice.html", order=order, items=items)


@app.route("/customers")
@login_required
def customers():
    rows = execute("""
        SELECT c.*, COUNT(o.id) orders_count, COALESCE(SUM(o.total),0) total_spent
        FROM customers c
        LEFT JOIN orders o ON o.customer_id = c.id
        GROUP BY c.id
        ORDER BY c.id DESC
    """, fetchall=True)

    return render_template("customers.html", customers=rows)


@app.route("/attendance", methods=["GET", "POST"])
@login_required
def attendance():
    if request.method == "POST":
        status = request.form.get("status","Present")

        execute("""
            INSERT INTO attendance(user_id, username, status, branch)
            VALUES(?,?,?,?)
        """, (
            session["user_id"],
            session["username"],
            status,
            session.get("branch","Main Branch")
        ), commit=True)

        log("ATTENDANCE", status)
        flash("Attendance marked.", "success")
        return redirect(url_for("attendance"))

    rows = execute("SELECT * FROM attendance ORDER BY id DESC LIMIT 100", fetchall=True)
    return render_template("attendance.html", rows=rows)


@app.route("/users")
@roles_required("master", "admin")
def users():
    if session.get("role") == "admin":
        rows = execute("SELECT * FROM users WHERE role='employee' ORDER BY id DESC", fetchall=True)
    else:
        rows = execute("SELECT * FROM users ORDER BY id DESC", fetchall=True)

    return render_template("users.html", users=rows)


@app.route("/users/add", methods=["POST"])
@roles_required("master", "admin")
def add_user():
    role = request.form.get("role")

    if session.get("role") == "admin" and role != "employee":
        flash("Admins can only create employee accounts.", "danger")
        return redirect(url_for("users"))

    try:
        execute("""
            INSERT INTO users(name, username, password_hash, role, branch)
            VALUES(?,?,?,?,?)
        """, (
            request.form["name"].strip(),
            request.form["username"].strip(),
            generate_password_hash(request.form["password"]),
            role,
            request.form.get("branch","Main Branch").strip()
        ), commit=True)

        flash("User created.", "success")

    except sqlite3.IntegrityError:
        flash("Username already exists.", "danger")

    return redirect(url_for("users"))


@app.route("/users/delete/<int:user_id>", methods=["POST"])
@roles_required("master", "admin")
def delete_user(user_id):
    target = execute("SELECT * FROM users WHERE id=?", (user_id,), fetchone=True)

    if not target:
        flash("User not found.", "danger")
        return redirect(url_for("users"))

    if target["username"] == "masteradmin":
        flash("Main account cannot be deleted.", "danger")
        return redirect(url_for("users"))

    if int(target["id"]) == int(session.get("user_id")):
        flash("You cannot delete your own logged-in account.", "danger")
        return redirect(url_for("users"))

    if session.get("role") == "admin" and target["role"] != "employee":
        flash("Admins can only delete employee accounts.", "danger")
        return redirect(url_for("users"))

    execute("DELETE FROM users WHERE id=?", (user_id,), commit=True)
    log("DELETE_USER", target["username"])
    flash("User deleted successfully.", "success")
    return redirect(url_for("users"))


@app.route("/reports")
@login_required
def reports():
    sales = execute("""
        SELECT date(created_at) day, COUNT(*) bills, COALESCE(SUM(total),0) revenue, COALESCE(SUM(profit),0) profit
        FROM orders
        GROUP BY date(created_at)
        ORDER BY day DESC
        LIMIT 30
    """, fetchall=True)

    low = execute("SELECT * FROM products WHERE quantity <= low_stock_limit ORDER BY quantity", fetchall=True)

    expiry = execute("""
        SELECT * FROM products 
        WHERE expiry_date!='' AND date(expiry_date) <= date('now','+7 day')
        ORDER BY expiry_date
    """, fetchall=True)

    return render_template("reports.html", sales=sales, low=low, expiry=expiry)


@app.route("/export/products.csv")
@roles_required("master", "admin")
def export_products():
    rows = execute("SELECT * FROM products ORDER BY id", fetchall=True)
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "id",
        "barcode",
        "name",
        "category",
        "brand",
        "cost_price",
        "selling_price",
        "quantity",
        "low_stock_limit",
        "expiry_date",
        "branch"
    ])

    for r in rows:
        writer.writerow([
            r["id"],
            r["barcode"],
            r["name"],
            r["category"],
            r["brand"],
            r["cost_price"],
            r["selling_price"],
            r["quantity"],
            r["low_stock_limit"],
            r["expiry_date"],
            r["branch"]
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition":"attachment; filename=stockitup_products.csv"}
    )


@app.route("/branches", methods=["GET", "POST"])
@roles_required("master")
def branches():
    if request.method == "POST":
        try:
            execute(
                "INSERT INTO branches(name, location) VALUES(?,?)",
                (request.form["name"], request.form.get("location","")),
                commit=True
            )
            flash("Branch added.", "success")

        except sqlite3.IntegrityError:
            flash("Branch already exists.", "danger")

        return redirect(url_for("branches"))

    rows = execute("SELECT * FROM branches ORDER BY id DESC", fetchall=True)
    return render_template("branches.html", branches=rows)


@app.route("/system")
@roles_required("master")
def system_panel():
    users_count = execute("SELECT COUNT(*) c FROM users", fetchone=True)["c"]
    products_count = execute("SELECT COUNT(*) c FROM products", fetchone=True)["c"]
    orders_count = execute("SELECT COUNT(*) c FROM orders", fetchone=True)["c"]
    logs = execute("SELECT * FROM activity_logs ORDER BY id DESC LIMIT 25", fetchall=True)

    return render_template(
        "system.html",
        users_count=users_count,
        products_count=products_count,
        orders_count=orders_count,
        logs=logs
    )


init_db()

if __name__ == "__main__":
    app.run(debug=True)