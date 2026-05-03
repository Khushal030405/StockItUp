import os
import csv
import io
import json
from datetime import datetime, date, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "stockitup-local-secret")

database_url = os.environ.get("DATABASE_URL", "sqlite:///stockitup.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

# Supabase/PostgreSQL on Render needs SSL.
if database_url.startswith("postgresql://") and "sslmode=" not in database_url:
    separator = "&" if "?" in database_url else "?"
    database_url = database_url + separator + "sslmode=require"

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
APP_NAME = "StockItUp"


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="employee")
    branch = db.Column(db.String(120), default="Main Branch")
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    brand = db.Column(db.String(100), default="")
    cost_price = db.Column(db.Float, default=0)
    selling_price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    low_stock_limit = db.Column(db.Integer, default=5)
    expiry_date = db.Column(db.String(20), default="")
    branch = db.Column(db.String(120), default="Main Branch")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    phone = db.Column(db.String(40), default="", index=True)
    email = db.Column(db.String(140), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_no = db.Column(db.String(80), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=True)
    customer_name = db.Column(db.String(140), default="Walk-in Customer")
    subtotal = db.Column(db.Float, default=0)
    discount = db.Column(db.Float, default=0)
    total = db.Column(db.Float, default=0)
    profit = db.Column(db.Float, default=0)
    payment_mode = db.Column(db.String(40), default="Cash")
    sold_by = db.Column(db.String(80))
    branch = db.Column(db.String(120), default="Main Branch")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    product_name = db.Column(db.String(180), nullable=False)
    barcode = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(100), default="")
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    cost_price = db.Column(db.Float, default=0)
    subtotal = db.Column(db.Float, nullable=False)


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    username = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(40), nullable=False)
    branch = db.Column(db.String(120), default="Main Branch")
    marked_at = db.Column(db.DateTime, default=datetime.utcnow)


class Branch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    location = db.Column(db.String(180), default="")
    active = db.Column(db.Boolean, default=True)


class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), default="system")
    action = db.Column(db.String(120))
    details = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def log(action, details=""):
    try:
        db.session.add(ActivityLog(username=session.get("username", "system"), action=action, details=details))
        db.session.commit()
    except Exception:
        db.session.rollback()


def seed_data():
    def add_user(name, username, password, role):
        username = username.lower()
        if not User.query.filter_by(username=username).first():
            db.session.add(User(
                name=name,
                username=username,
                password_hash=generate_password_hash(password),
                role=role,
                branch="Main Branch"
            ))

    add_user("Master Admin", "masteradmin", "admin123", "master")
    add_user("Branch Admin", "admin", "admin123", "admin")
    add_user("Employee", "employee", "emp123", "employee")

    if not Branch.query.filter_by(name="Main Branch").first():
        db.session.add(Branch(name="Main Branch", location="Default Location"))

    samples = [
        ("8901000000011", "Premium Notebook", "Stationery", "Classmate", 35, 60, 25, 5, ""),
        ("8901000000028", "Blue Ball Pen", "Stationery", "Cello", 5, 10, 80, 10, ""),
        ("8901000000035", "Wireless Mouse", "Electronics", "LogiTech", 320, 499, 12, 4, ""),
        ("8901000000042", "USB Cable Type-C", "Electronics", "StockItUp", 70, 149, 3, 5, ""),
        ("8901000000059", "Cold Coffee", "Beverages", "Cafe", 20, 50, 18, 8, (date.today()+timedelta(days=5)).isoformat()),
    ]
    for barcode, name, cat, brand, cost, price, qty, low, exp in samples:
        if not Product.query.filter_by(barcode=barcode).first():
            db.session.add(Product(
                barcode=barcode, name=name, category=cat, brand=brand,
                cost_price=cost, selling_price=price, quantity=qty,
                low_stock_limit=low, expiry_date=exp
            ))
    db.session.commit()


def setup_database():
    db.create_all()
    seed_data()


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


@app.route("/healthz")
def healthz():
    return "ok", 200


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter(db.func.lower(User.username) == username, User.active == True).first()
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            session["username"] = user.username
            session["name"] = user.name
            session["role"] = user.role
            session["branch"] = user.branch
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
    today_start = datetime.combine(date.today(), datetime.min.time())
    product_count = Product.query.count()
    low_stock = Product.query.filter(Product.quantity <= Product.low_stock_limit).count()
    expiry_limit = date.today() + timedelta(days=7)
    expiry_soon = Product.query.filter(Product.expiry_date != "", Product.expiry_date <= expiry_limit.isoformat()).count()

    todays_orders = Order.query.filter(Order.created_at >= today_start).all()
    today_sales = sum(o.total for o in todays_orders)
    today_profit = sum(o.profit for o in todays_orders)

    employees_present = db.session.query(Attendance.username).filter(
        Attendance.marked_at >= today_start,
        Attendance.status == "Present"
    ).distinct().count()

    recent_orders = Order.query.order_by(Order.id.desc()).limit(6).all()

    daily_labels, daily_values = [], []
    for i in range(6, -1, -1):
        d = date.today() - timedelta(days=i)
        start = datetime.combine(d, datetime.min.time())
        end = start + timedelta(days=1)
        total = db.session.query(db.func.coalesce(db.func.sum(Order.total), 0)).filter(Order.created_at >= start, Order.created_at < end).scalar()
        daily_labels.append(d.isoformat())
        daily_values.append(float(total or 0))

    top_rows = db.session.query(OrderItem.product_name, db.func.sum(OrderItem.quantity).label("qty")).group_by(OrderItem.product_name).order_by(db.desc("qty")).limit(5).all()
    top_labels = [r.product_name for r in top_rows]
    top_values = [int(r.qty) for r in top_rows]

    ai_note = "Sales look stable. Keep monitoring inventory health."
    if low_stock:
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
        daily_labels=daily_labels,
        daily_values=daily_values,
        top_labels=top_labels,
        top_values=top_values,
        ai_note=ai_note
    )


@app.route("/inventory")
@login_required
def inventory():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    query = Product.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Product.name.ilike(like), Product.barcode.ilike(like), Product.brand.ilike(like)))
    if category:
        query = query.filter_by(category=category)
    products = query.order_by(Product.id.desc()).all()
    categories = [r[0] for r in db.session.query(Product.category).distinct().order_by(Product.category).all()]
    return render_template("inventory.html", products=products, categories=categories, q=q, selected_category=category)


@app.route("/inventory/add", methods=["GET", "POST"])
@login_required
def add_product():
    if request.method == "POST":
        barcode = request.form["barcode"].strip()
        if Product.query.filter_by(barcode=barcode).first():
            flash("Barcode already exists.", "danger")
            return redirect(url_for("add_product"))
        p = Product(
            barcode=barcode,
            name=request.form["name"].strip(),
            category=request.form["category"].strip(),
            brand=request.form.get("brand","").strip(),
            cost_price=float(request.form.get("cost_price") or 0),
            selling_price=float(request.form["selling_price"]),
            quantity=int(request.form["quantity"]),
            low_stock_limit=int(request.form.get("low_stock_limit") or 5),
            expiry_date=request.form.get("expiry_date",""),
            branch=session.get("branch","Main Branch")
        )
        db.session.add(p)
        db.session.commit()
        log("ADD_PRODUCT", p.name)
        flash("Product added successfully.", "success")
        return redirect(url_for("inventory"))
    return render_template("product_form.html", product=None)


@app.route("/inventory/edit/<int:product_id>", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == "POST":
        product.barcode = request.form["barcode"].strip()
        product.name = request.form["name"].strip()
        product.category = request.form["category"].strip()
        product.brand = request.form.get("brand","").strip()
        product.cost_price = float(request.form.get("cost_price") or 0)
        product.selling_price = float(request.form["selling_price"])
        product.quantity = int(request.form["quantity"])
        product.low_stock_limit = int(request.form.get("low_stock_limit") or 5)
        product.expiry_date = request.form.get("expiry_date","")
        db.session.commit()
        log("EDIT_PRODUCT", product.name)
        flash("Product updated.", "success")
        return redirect(url_for("inventory"))
    return render_template("product_form.html", product=product)


@app.route("/inventory/delete/<int:product_id>", methods=["GET", "POST"])
@roles_required("master", "admin")
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    product_name = product.name
    db.session.delete(product)
    db.session.commit()
    log("DELETE_PRODUCT", product_name)
    flash("Product deleted successfully.", "success")
    return redirect(url_for("inventory"))


@app.route("/scanner")
@login_required
def scanner():
    return render_template("scanner.html")


@app.route("/api/product/<barcode>")
@login_required
def api_product(barcode):
    p = Product.query.filter_by(barcode=barcode).first()
    if not p:
        return jsonify({"ok": False, "message": "Product not found"})
    return jsonify({"ok": True, "product": {
        "id": p.id, "barcode": p.barcode, "name": p.name, "category": p.category,
        "brand": p.brand, "cost_price": p.cost_price, "selling_price": p.selling_price,
        "quantity": p.quantity, "low_stock_limit": p.low_stock_limit, "expiry_date": p.expiry_date
    }})


@app.route("/billing", methods=["GET", "POST"])
@login_required
def billing():
    if request.method == "POST":
        try:
            items = json.loads(request.form.get("items_json", "[]"))
        except Exception:
            flash("Cart data could not be read. Please add products again.", "danger")
            return redirect(url_for("billing"))

        if not isinstance(items, list) or not items:
            flash("Cart is empty. Please add at least one product.", "danger")
            return redirect(url_for("billing"))

        customer_name = request.form.get("customer_name","Walk-in Customer").strip() or "Walk-in Customer"
        customer_phone = request.form.get("customer_phone","").strip()
        payment_mode = request.form.get("payment_mode","Cash")
        discount = float(request.form.get("discount") or 0)

        subtotal = 0
        profit = 0
        checked = []

        try:
            for item in items:
                p = Product.query.filter_by(barcode=str(item["barcode"]).strip()).with_for_update().first()
                qty = int(item["qty"])
                if not p:
                    raise ValueError(f"Product not found: {item['barcode']}")
                if qty <= 0:
                    raise ValueError("Quantity must be positive.")
                if p.quantity < qty:
                    raise ValueError(f"Not enough stock for {p.name}. Available: {p.quantity}")
                subtotal += qty * p.selling_price
                profit += qty * (p.selling_price - p.cost_price)
                checked.append((p, qty))

            total = max(subtotal - discount, 0)
            customer_id = None
            if customer_phone:
                customer = Customer.query.filter_by(phone=customer_phone).first()
                if not customer:
                    customer = Customer(name=customer_name, phone=customer_phone)
                    db.session.add(customer)
                    db.session.flush()
                customer_id = customer.id

            invoice_no = "INV" + datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]
            order = Order(
                invoice_no=invoice_no,
                customer_id=customer_id,
                customer_name=customer_name,
                subtotal=subtotal,
                discount=discount,
                total=total,
                profit=profit,
                payment_mode=payment_mode,
                sold_by=session["username"],
                branch=session.get("branch","Main Branch")
            )
            db.session.add(order)
            db.session.flush()

            for p, qty in checked:
                db.session.add(OrderItem(
                    order_id=order.id,
                    product_id=p.id,
                    product_name=p.name,
                    barcode=p.barcode,
                    category=p.category,
                    quantity=qty,
                    price=p.selling_price,
                    cost_price=p.cost_price,
                    subtotal=qty * p.selling_price
                ))
                p.quantity -= qty

            db.session.commit()
            log("SALE", invoice_no)
            flash("Bill generated successfully.", "success")
            return redirect(url_for("invoice", order_id=order.id))
        except Exception as e:
            db.session.rollback()
            flash(str(e), "danger")
            return redirect(url_for("billing"))

    products = Product.query.filter(Product.quantity > 0).order_by(Product.name).all()
    return render_template("billing.html", products=products)


@app.route("/invoice/<int:order_id>")
@login_required
def invoice(order_id):
    order = Order.query.get_or_404(order_id)
    items = OrderItem.query.filter_by(order_id=order.id).all()
    return render_template("invoice.html", order=order, items=items)


@app.route("/customers")
@login_required
def customers():
    rows = []
    for c in Customer.query.order_by(Customer.id.desc()).all():
        orders = Order.query.filter_by(customer_id=c.id).all()
        c.orders_count = len(orders)
        c.total_spent = sum(o.total for o in orders)
        rows.append(c)
    return render_template("customers.html", customers=rows)


@app.route("/attendance", methods=["GET", "POST"])
@login_required
def attendance():
    if request.method == "POST":
        selected_user_id = request.form.get("user_id")

        # Employees can only mark their own attendance.
        if session.get("role") == "employee":
            selected_user_id = session.get("user_id")

        user = User.query.get(int(selected_user_id)) if selected_user_id else None
        if not user or not user.active:
            flash("Please select a valid active user.", "danger")
            return redirect(url_for("attendance"))

        status = request.form.get("status", "Present")
        if status not in ["Present", "Absent", "Break", "Left"]:
            status = "Present"

        a = Attendance(
            user_id=user.id,
            username=user.username,
            status=status,
            branch=user.branch or session.get("branch", "Main Branch")
        )
        db.session.add(a)
        db.session.commit()
        log("ATTENDANCE", f"{user.username} - {status}")
        flash(f"Attendance marked for {user.name}: {status}.", "success")
        return redirect(url_for("attendance"))

    if session.get("role") == "employee":
        users_list = [User.query.get(session["user_id"])]
    elif session.get("role") == "admin":
        users_list = User.query.filter(User.role == "employee", User.active == True).order_by(User.name).all()
    else:
        users_list = User.query.filter(User.active == True).order_by(User.role, User.name).all()

    rows = Attendance.query.order_by(Attendance.id.desc()).limit(200).all()

    summary_rows = db.session.query(
        Attendance.username,
        db.func.count(db.func.distinct(db.func.date(Attendance.marked_at))).label("total_days"),
        db.func.sum(db.case((Attendance.status == "Present", 1), else_=0)).label("present_count"),
        db.func.sum(db.case((Attendance.status == "Absent", 1), else_=0)).label("absent_count"),
        db.func.max(Attendance.marked_at).label("last_marked")
    ).group_by(Attendance.username).order_by(Attendance.username).all()

    return render_template(
        "attendance.html",
        rows=rows,
        users_list=users_list,
        summary_rows=summary_rows
    )


@app.route("/users")
@roles_required("master", "admin")
def users():
    if session.get("role") == "admin":
        rows = User.query.filter_by(role="employee").order_by(User.id.desc()).all()
    else:
        rows = User.query.order_by(User.id.desc()).all()
    return render_template("users.html", users=rows)


@app.route("/users/add", methods=["POST"])
@roles_required("master", "admin")
def add_user():
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    role = request.form.get("role", "employee").strip()
    branch = request.form.get("branch", "Main Branch").strip() or "Main Branch"

    if not name or not username or not password:
        flash("Name, username, and password are required.", "danger")
        return redirect(url_for("users"))
    if role not in ["master", "admin", "employee"]:
        role = "employee"
    if session.get("role") == "admin" and role != "employee":
        flash("Admins can only create employee accounts.", "danger")
        return redirect(url_for("users"))
    if User.query.filter_by(username=username).first():
        flash("Username already exists.", "danger")
        return redirect(url_for("users"))

    db.session.add(User(name=name, username=username, password_hash=generate_password_hash(password), role=role, branch=branch))
    db.session.commit()
    log("CREATE_USER", username)
    flash(f"User '{username}' created successfully.", "success")
    return redirect(url_for("users"))


@app.route("/users/delete/<int:user_id>", methods=["POST"])
@roles_required("master", "admin")
def delete_user(user_id):
    target = User.query.get_or_404(user_id)
    if target.username == "masteradmin":
        flash("Main account cannot be deleted.", "danger")
        return redirect(url_for("users"))
    if target.id == session.get("user_id"):
        flash("You cannot delete your own logged-in account.", "danger")
        return redirect(url_for("users"))
    if session.get("role") == "admin" and target.role != "employee":
        flash("Admins can only delete employee accounts.", "danger")
        return redirect(url_for("users"))
    db.session.delete(target)
    db.session.commit()
    log("DELETE_USER", target.username)
    flash("User deleted successfully.", "success")
    return redirect(url_for("users"))


@app.route("/reports")
@login_required
def reports():
    sales = db.session.query(
        db.func.date(Order.created_at).label("day"),
        db.func.count(Order.id).label("bills"),
        db.func.coalesce(db.func.sum(Order.total), 0).label("revenue"),
        db.func.coalesce(db.func.sum(Order.profit), 0).label("profit")
    ).group_by(db.func.date(Order.created_at)).order_by(db.desc("day")).limit(30).all()

    low = Product.query.filter(Product.quantity <= Product.low_stock_limit).order_by(Product.quantity).all()
    expiry_limit = date.today() + timedelta(days=7)
    expiry = Product.query.filter(Product.expiry_date != "", Product.expiry_date <= expiry_limit.isoformat()).order_by(Product.expiry_date).all()
    return render_template("reports.html", sales=sales, low=low, expiry=expiry)


@app.route("/export/products.csv")
@roles_required("master", "admin")
def export_products():
    rows = Product.query.order_by(Product.id).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id","barcode","name","category","brand","cost_price","selling_price","quantity","low_stock_limit","expiry_date","branch"])
    for r in rows:
        writer.writerow([r.id,r.barcode,r.name,r.category,r.brand,r.cost_price,r.selling_price,r.quantity,r.low_stock_limit,r.expiry_date,r.branch])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment; filename=stockitup_products.csv"})


@app.route("/branches", methods=["GET", "POST"])
@roles_required("master")
def branches():
    if request.method == "POST":
        name = request.form["name"].strip()
        if not Branch.query.filter_by(name=name).first():
            db.session.add(Branch(name=name, location=request.form.get("location","")))
            db.session.commit()
            flash("Branch added.", "success")
        else:
            flash("Branch already exists.", "danger")
        return redirect(url_for("branches"))
    rows = Branch.query.order_by(Branch.id.desc()).all()
    return render_template("branches.html", branches=rows)


@app.route("/system")
@roles_required("master")
def system_panel():
    logs = ActivityLog.query.order_by(ActivityLog.id.desc()).limit(25).all()
    return render_template("system.html", users_count=User.query.count(), products_count=Product.query.count(), orders_count=Order.query.count(), logs=logs)


with app.app_context():
    try:
        setup_database()
    except Exception as e:
        print("DATABASE_STARTUP_ERROR:", repr(e), flush=True)
        raise


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
