from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify, Response
import sqlite3
from datetime import datetime, date, timedelta
from functools import wraps
import csv
import io
import json
from werkzeug.security import generate_password_hash, check_password_hash

APP_NAME = "StockItUp"
DB_PATH = "stockitup.db"

app = Flask(__name__)
app.secret_key = "stockitup_secret"


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

    c.execute("SELECT COUNT(*) AS count FROM users")
    user_count = c.fetchone()["count"]

    if user_count == 0:
        c.execute("""
            INSERT INTO users(name, username, password_hash, role, branch)
            VALUES(?,?,?,?,?)
        """, ("Master Admin", "masteradmin", generate_password_hash("admin123"), "master", "Main Branch"))

        c.execute("""
            INSERT INTO users(name, username, password_hash, role, branch)
            VALUES(?,?,?,?,?)
        """, ("Branch Admin", "admin", generate_password_hash("admin123"), "admin", "Main Branch"))

        c.execute("""
            INSERT INTO users(name, username, password_hash, role, branch)
            VALUES(?,?,?,?,?)
        """, ("Employee", "employee", generate_password_hash("emp123"), "employee", "Main Branch"))

    c.execute("INSERT OR IGNORE INTO branches(name, location) VALUES('Main Branch','Default Location')")

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


def selected_branch():
    if session.get("role") == "master":
        return request.args.get("branch", "").strip()
    return session.get("branch", "Main Branch")


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
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = execute("SELECT * FROM users WHERE LOWER(username)=? AND active=1", (username,), fetchone=True)

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
    branch = selected_branch()

    where = ""
    params = []

    if branch:
        where = " WHERE branch=?"
        params.append(branch)

    product_count = execute(f"SELECT COUNT(*) c FROM products{where}", params, fetchone=True)["c"]
    user_count = execute(f"SELECT COUNT(*) c FROM users{where}", params, fetchone=True)["c"]
    low_stock = execute(
        f"SELECT COUNT(*) c FROM products{where + ' AND' if branch else ' WHERE'} quantity <= low_stock_limit",
        params,
        fetchone=True
    )["c"]

    total_sales = execute(f"SELECT COALESCE(SUM(total),0) total FROM orders{where}", params, fetchone=True)["total"]
    total_profit = execute(f"SELECT COALESCE(SUM(profit),0) profit FROM orders{where}", params, fetchone=True)["profit"]

    recent_orders = execute(
        f"SELECT * FROM orders{where} ORDER BY id DESC LIMIT 8",
        params,
        fetchall=True
    )

    branches = execute("SELECT * FROM branches WHERE active=1 ORDER BY name", fetchall=True)

    return render_template(
        "dashboard.html",
        selected_branch=branch,
        branches=branches,
        product_count=product_count,
        user_count=user_count,
        low_stock=low_stock,
        total_sales=total_sales,
        total_profit=total_profit,
        recent_orders=recent_orders
    )


@app.route("/inventory")
@login_required
def inventory():
    branch = selected_branch()
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()

    sql = "SELECT * FROM products WHERE 1=1"
    params = []

    if session.get("role") != "master":
        sql += " AND branch=?"
        params.append(session.get("branch", "Main Branch"))
    elif branch:
        sql += " AND branch=?"
        params.append(branch)

    if q:
        sql += " AND (name LIKE ? OR barcode LIKE ? OR brand LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]

    if category:
        sql += " AND category=?"
        params.append(category)

    sql += " ORDER BY id DESC"

    products = execute(sql, params, fetchall=True)
    categories = execute("SELECT DISTINCT category FROM products ORDER BY category", fetchall=True)
    branches = execute("SELECT * FROM branches WHERE active=1 ORDER BY name", fetchall=True)

    return render_template(
        "inventory.html",
        products=products,
        categories=categories,
        branches=branches,
        selected_branch=branch,
        q=q,
        selected_category=category
    )


@app.route("/inventory/add", methods=["GET", "POST"])
@login_required
def add_product():
    if request.method == "POST":
        product_branch = request.form.get("branch", session.get("branch", "Main Branch")).strip()

        if session.get("role") != "master":
            product_branch = session.get("branch", "Main Branch")

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
                product_branch
            ), commit=True)
            log("ADD_PRODUCT", request.form["name"])
            flash("Product added successfully.", "success")
            return redirect(url_for("inventory"))
        except sqlite3.IntegrityError:
            flash("Barcode already exists.", "danger")
        except Exception as e:
            flash(f"Could not add product: {e}", "danger")

    branches = execute("SELECT * FROM branches WHERE active=1 ORDER BY name", fetchall=True)
    return render_template("product_form.html", product=None, branches=branches)


@app.route("/inventory/edit/<int:product_id>", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    product = execute("SELECT * FROM products WHERE id=?", (product_id,), fetchone=True)

    if not product:
        flash("Product not found.", "danger")
        return redirect(url_for("inventory"))

    if session.get("role") != "master" and product["branch"] != session.get("branch"):
        flash("Access denied.", "danger")
        return redirect(url_for("inventory"))

    if request.method == "POST":
        product_branch = request.form.get("branch", product["branch"]).strip()

        if session.get("role") != "master":
            product_branch = session.get("branch", "Main Branch")

        execute("""
            UPDATE products SET barcode=?, name=?, category=?, brand=?, cost_price=?, selling_price=?,
            quantity=?, low_stock_limit=?, expiry_date=?, branch=? WHERE id=?
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
            product_branch,
            product_id
        ), commit=True)
        log("EDIT_PRODUCT", request.form["name"])
        flash("Product updated.", "success")
        return redirect(url_for("inventory"))

    branches = execute("SELECT * FROM branches WHERE active=1 ORDER BY name", fetchall=True)
    return render_template("product_form.html", product=product, branches=branches)


@app.route("/inventory/delete/<int:product_id>", methods=["POST"])
@roles_required("master", "admin")
def delete_product(product_id):
    product = execute("SELECT * FROM products WHERE id=?", (product_id,), fetchone=True)

    if not product:
        flash("Product not found.", "danger")
        return redirect(url_for("inventory"))

    if session.get("role") != "master" and product["branch"] != session.get("branch"):
        flash("Access denied.", "danger")
        return redirect(url_for("inventory"))

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
    branch = request.args.get("branch", session.get("branch", "Main Branch"))

    if session.get("role") == "master":
        if branch:
            p = execute("SELECT * FROM products WHERE barcode=? AND branch=?", (barcode.strip(), branch), fetchone=True)
        else:
            p = execute("SELECT * FROM products WHERE barcode=?", (barcode.strip(),), fetchone=True)
    else:
        p = execute(
            "SELECT * FROM products WHERE barcode=? AND branch=?",
            (barcode.strip(), session.get("branch", "Main Branch")),
            fetchone=True
        )

    if not p:
        return jsonify({"ok": False, "message": "Product not found"})

    return jsonify({"ok": True, "product": dict(p)})


@app.route("/billing", methods=["GET", "POST"])
@login_required
def billing():
    bill_branch = selected_branch()

    if session.get("role") != "master":
        bill_branch = session.get("branch", "Main Branch")

    if request.method == "POST":
        raw_items = request.form.get("items_json", "[]")
        bill_branch = request.form.get("branch", bill_branch).strip()

        if session.get("role") != "master":
            bill_branch = session.get("branch", "Main Branch")

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

                c.execute("SELECT * FROM products WHERE barcode=? AND branch=?", (barcode, bill_branch))
                p = c.fetchone()

                if not p:
                    raise Exception(f"Product not found in {bill_branch}: {barcode}")

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
            else:
                c.execute("INSERT INTO customers(name, phone) VALUES(?,?)", (customer_name, ""))
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
                bill_branch
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

    if session.get("role") == "master" and bill_branch:
        products = execute("SELECT * FROM products WHERE quantity > 0 AND branch=? ORDER BY name", (bill_branch,), fetchall=True)
    elif session.get("role") == "master":
        products = execute("SELECT * FROM products WHERE quantity > 0 ORDER BY name", fetchall=True)
    else:
        products = execute(
            "SELECT * FROM products WHERE quantity > 0 AND branch=? ORDER BY name",
            (session.get("branch", "Main Branch"),),
            fetchall=True
        )

    branches = execute("SELECT * FROM branches WHERE active=1 ORDER BY name", fetchall=True)

    return render_template(
        "billing.html",
        products=products,
        branches=branches,
        selected_branch=bill_branch
    )


@app.route("/invoice/<int:order_id>")
@login_required
def invoice(order_id):
    order = execute("SELECT * FROM orders WHERE id=?", (order_id,), fetchone=True)
    items = execute("SELECT * FROM order_items WHERE order_id=?", (order_id,), fetchall=True)

    if not order:
        flash("Invoice not found.", "danger")
        return redirect(url_for("billing"))

    if session.get("role") != "master" and order["branch"] != session.get("branch"):
        flash("Access denied.", "danger")
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
        selected_user_id = request.form.get("user_id")

        if session.get("role") == "employee":
            selected_user_id = session.get("user_id")

        user = execute("SELECT * FROM users WHERE id=? AND active=1", (selected_user_id,), fetchone=True)

        if not user:
            flash("Please select a valid active user.", "danger")
            return redirect(url_for("attendance"))

        status = request.form.get("status", "Present")

        execute("""
            INSERT INTO attendance(user_id, username, status, branch)
            VALUES(?,?,?,?)
        """, (
            user["id"],
            user["username"],
            status,
            user["branch"]
        ), commit=True)

        log("ATTENDANCE", status)
        flash("Attendance marked.", "success")
        return redirect(url_for("attendance"))

    if session.get("role") == "master":
        users_list = execute("SELECT * FROM users WHERE active=1 ORDER BY name", fetchall=True)
    elif session.get("role") == "admin":
        users_list = execute(
            "SELECT * FROM users WHERE role='employee' AND active=1 AND branch=? ORDER BY name",
            (session.get("branch"),),
            fetchall=True
        )
    else:
        users_list = execute("SELECT * FROM users WHERE id=?", (session.get("user_id"),), fetchall=True)

    rows = execute("SELECT * FROM attendance ORDER BY id DESC LIMIT 100", fetchall=True)

    return render_template("attendance.html", rows=rows, users_list=users_list)


@app.route("/users")
@roles_required("master", "admin")
def users():
    if session.get("role") == "admin":
        rows = execute("SELECT * FROM users WHERE role='employee' AND branch=? ORDER BY id DESC", (session.get("branch"),), fetchall=True)
    else:
        rows = execute("SELECT * FROM users ORDER BY id DESC", fetchall=True)

    branches = execute("SELECT * FROM branches WHERE active=1 ORDER BY name", fetchall=True)

    return render_template("users.html", users=rows, branches=branches)


@app.route("/users/add", methods=["POST"])
@roles_required("master", "admin")
def add_user():
    role = request.form.get("role")
    username = request.form["username"].strip().lower()
    user_branch = request.form.get("branch", session.get("branch", "Main Branch")).strip()

    if session.get("role") == "admin":
        role = "employee"
        user_branch = session.get("branch", "Main Branch")

    try:
        execute("""
            INSERT INTO users(name, username, password_hash, role, branch)
            VALUES(?,?,?,?,?)
        """, (
            request.form["name"].strip(),
            username,
            generate_password_hash(request.form["password"]),
            role,
            user_branch
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


@app.route("/users/toggle/<int:user_id>", methods=["POST"])
@roles_required("master", "admin")
def toggle_user(user_id):
    target = execute("SELECT * FROM users WHERE id=?", (user_id,), fetchone=True)

    if not target:
        flash("User not found.", "danger")
        return redirect(url_for("users"))

    if target["username"] == "masteradmin":
        flash("Master admin cannot be deactivated.", "danger")
        return redirect(url_for("users"))

    if session.get("role") == "admin" and target["role"] != "employee":
        flash("Admins can only control employees.", "danger")
        return redirect(url_for("users"))

    new_status = 0 if target["active"] == 1 else 1

    execute("UPDATE users SET active=? WHERE id=?", (new_status, user_id), commit=True)

    flash("User status updated.", "success")
    return redirect(url_for("users"))


@app.route("/reports")
@login_required
def reports():
    branch = selected_branch()

    where = ""
    params = []

    if session.get("role") != "master":
        where = " WHERE branch=?"
        params.append(session.get("branch", "Main Branch"))
    elif branch:
        where = " WHERE branch=?"
        params.append(branch)

    sales = execute(f"""
        SELECT date(created_at) day, branch, COUNT(*) bills, COALESCE(SUM(total),0) revenue, COALESCE(SUM(profit),0) profit
        FROM orders
        {where}
        GROUP BY date(created_at), branch
        ORDER BY day DESC
        LIMIT 30
    """, params, fetchall=True)

    low = execute(
        f"SELECT * FROM products {where} {'AND' if where else 'WHERE'} quantity <= low_stock_limit ORDER BY quantity",
        params,
        fetchall=True
    )

    expiry = execute(
        f"""
        SELECT * FROM products
        {where} {'AND' if where else 'WHERE'} expiry_date!='' AND date(expiry_date) <= date('now','+7 day')
        ORDER BY expiry_date
        """,
        params,
        fetchall=True
    )

    branches = execute("SELECT * FROM branches WHERE active=1 ORDER BY name", fetchall=True)

    return render_template(
        "reports.html",
        sales=sales,
        low=low,
        expiry=expiry,
        branches=branches,
        selected_branch=branch
    )


@app.route("/export/products.csv")
@roles_required("master", "admin")
def export_products():
    branch = selected_branch()

    if session.get("role") == "master" and branch:
        rows = execute("SELECT * FROM products WHERE branch=? ORDER BY id", (branch,), fetchall=True)
    elif session.get("role") == "master":
        rows = execute("SELECT * FROM products ORDER BY id", fetchall=True)
    else:
        rows = execute("SELECT * FROM products WHERE branch=? ORDER BY id", (session.get("branch"),), fetchall=True)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "id", "barcode", "name", "category", "brand", "cost_price",
        "selling_price", "quantity", "low_stock_limit", "expiry_date", "branch"
    ])

    for r in rows:
        writer.writerow([
            r["id"], r["barcode"], r["name"], r["category"], r["brand"],
            r["cost_price"], r["selling_price"], r["quantity"],
            r["low_stock_limit"], r["expiry_date"], r["branch"]
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
                "INSERT INTO branches(name, location, active) VALUES(?,?,1)",
                (
                    request.form["name"].strip(),
                    request.form.get("location", "").strip()
                ),
                commit=True
            )
            flash("Branch added.", "success")

        except sqlite3.IntegrityError:
            flash("Branch already exists.", "danger")

        return redirect(url_for("branches"))

    rows = execute("SELECT * FROM branches ORDER BY id DESC", fetchall=True)
    return render_template("branches.html", branches=rows)


@app.route("/branches/toggle/<int:branch_id>", methods=["POST"])
@roles_required("master")
def toggle_branch(branch_id):
    branch = execute("SELECT * FROM branches WHERE id=?", (branch_id,), fetchone=True)

    if not branch:
        flash("Branch not found.", "danger")
        return redirect(url_for("branches"))

    new_status = 0 if branch["active"] == 1 else 1

    execute("UPDATE branches SET active=? WHERE id=?", (new_status, branch_id), commit=True)

    flash("Branch status updated.", "success")
    return redirect(url_for("branches"))


@app.route("/branches/delete/<int:branch_id>", methods=["POST"])
@roles_required("master")
def delete_branch(branch_id):
    branch = execute("SELECT * FROM branches WHERE id=?", (branch_id,), fetchone=True)

    if not branch:
        flash("Branch not found.", "danger")
        return redirect(url_for("branches"))

    if branch["name"] == "Main Branch":
        flash("Main Branch cannot be deleted.", "danger")
        return redirect(url_for("branches"))

    execute("DELETE FROM branches WHERE id=?", (branch_id,), commit=True)

    flash("Branch deleted successfully.", "success")
    return redirect(url_for("branches"))


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