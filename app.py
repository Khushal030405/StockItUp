from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify, Response
import sqlite3
from datetime import datetime, date, timedelta
from functools import wraps
import csv, io, json
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

    # USERS
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, username TEXT UNIQUE, password_hash TEXT,
        role TEXT, branch TEXT, active INTEGER DEFAULT 1
    )""")

    # PRODUCTS
    c.execute("""CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        barcode TEXT UNIQUE, name TEXT, category TEXT,
        brand TEXT, cost_price REAL, selling_price REAL,
        quantity INTEGER, low_stock_limit INTEGER,
        expiry_date TEXT
    )""")

    # CUSTOMERS
    c.execute("""CREATE TABLE IF NOT EXISTS customers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, phone TEXT
    )""")

    # ORDERS
    c.execute("""CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_no TEXT, customer_id INTEGER,
        customer_name TEXT, total REAL, profit REAL
    )""")

    # ORDER ITEMS
    c.execute("""CREATE TABLE IF NOT EXISTS order_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER, product_name TEXT,
        barcode TEXT, quantity INTEGER, price REAL
    )""")

    # BRANCHES
    c.execute("""CREATE TABLE IF NOT EXISTS branches(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE, location TEXT, active INTEGER DEFAULT 1
    )""")

    # CREATE DEFAULT USERS ONLY ONCE
    c.execute("SELECT COUNT(*) as c FROM users")
    if c.fetchone()["c"] == 0:
        c.execute("INSERT INTO users(name,username,password_hash,role,branch) VALUES(?,?,?,?,?)",
                  ("Master Admin","masteradmin",generate_password_hash("admin123"),"master","Main"))
        c.execute("INSERT INTO users(name,username,password_hash,role,branch) VALUES(?,?,?,?,?)",
                  ("Admin","admin",generate_password_hash("admin123"),"admin","Main"))

    # ONLY MAIN BRANCH
    c.execute("INSERT OR IGNORE INTO branches(name,location) VALUES('Main','Default')")

    conn.commit()
    conn.close()


init_db()


def login_required(f):
    @wraps(f)
    def wrapper(*a, **k):
        if "user_id" not in session:
            return redirect("/login")
        return f(*a, **k)
    return wrapper


def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*a, **k):
            if session.get("role") not in roles:
                flash("Access denied")
                return redirect("/dashboard")
            return f(*a, **k)
        return wrapper
    return decorator


@app.route("/")
def home():
    return redirect("/login")


@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        username = request.form["username"].lower()
        password = request.form["password"]

        user = execute("SELECT * FROM users WHERE LOWER(username)=? AND active=1",
                       (username,), fetchone=True)

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"]=user["id"]
            session["role"]=user["role"]
            return redirect("/dashboard")

        flash("Invalid login")

    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


# ---------------- USERS ---------------- #

@app.route("/users")
@roles_required("master","admin")
def users():
    data = execute("SELECT * FROM users", fetchall=True)
    return render_template("users.html", users=data)


@app.route("/users/add", methods=["POST"])
@roles_required("master","admin")
def add_user():
    try:
        execute("INSERT INTO users(name,username,password_hash,role,branch) VALUES(?,?,?,?,?)",
                (request.form["name"],
                 request.form["username"].lower(),
                 generate_password_hash(request.form["password"]),
                 request.form["role"],
                 "Main"),
                commit=True)
    except:
        flash("User exists")
    return redirect("/users")


@app.route("/users/delete/<int:id>", methods=["POST"])
@roles_required("master","admin")
def delete_user(id):
    execute("DELETE FROM users WHERE id=?", (id,), commit=True)
    return redirect("/users")


@app.route("/users/toggle/<int:id>", methods=["POST"])
@roles_required("master","admin")
def toggle_user(id):
    user = execute("SELECT * FROM users WHERE id=?", (id,), fetchone=True)
    new = 0 if user["active"] else 1
    execute("UPDATE users SET active=? WHERE id=?", (new,id), commit=True)
    return redirect("/users")


# ---------------- BRANCH ---------------- #

@app.route("/branches", methods=["GET","POST"])
@roles_required("master")
def branches():
    if request.method=="POST":
        try:
            execute("INSERT INTO branches(name,location) VALUES(?,?)",
                    (request.form["name"], request.form["location"]),
                    commit=True)
        except:
            flash("Exists")
    data = execute("SELECT * FROM branches", fetchall=True)
    return render_template("branches.html", branches=data)


@app.route("/branches/delete/<int:id>", methods=["POST"])
@roles_required("master")
def delete_branch(id):
    execute("DELETE FROM branches WHERE id=?", (id,), commit=True)
    return redirect("/branches")


@app.route("/branches/toggle/<int:id>", methods=["POST"])
@roles_required("master")
def toggle_branch(id):
    b = execute("SELECT * FROM branches WHERE id=?", (id,), fetchone=True)
    new = 0 if b["active"] else 1
    execute("UPDATE branches SET active=? WHERE id=?", (new,id), commit=True)
    return redirect("/branches")


# ---------------- BILLING ---------------- #

@app.route("/billing", methods=["GET","POST"])
@login_required
def billing():
    if request.method=="POST":
        items = json.loads(request.form.get("items_json","[]"))

        customer_name = request.form.get("customer_name","Walk-in")
        phone = request.form.get("phone","")

        conn=db()
        c=conn.cursor()

        subtotal=0
        for i in items:
            p = execute("SELECT * FROM products WHERE barcode=?", (i["barcode"],), fetchone=True)
            subtotal += p["selling_price"]*i["qty"]

        # SAVE CUSTOMER EVEN IF NO PHONE
        c.execute("INSERT INTO customers(name,phone) VALUES(?,?)",(customer_name,phone))
        customer_id=c.lastrowid

        invoice="INV"+datetime.now().strftime("%H%M%S")

        c.execute("INSERT INTO orders(invoice_no,customer_id,customer_name,total,profit) VALUES(?,?,?,?,?)",
                  (invoice,customer_id,customer_name,subtotal,0))

        conn.commit()
        conn.close()

        return redirect("/dashboard")

    return render_template("billing.html")


# ---------------- CUSTOMERS ---------------- #

@app.route("/customers")
@login_required
def customers():
    data = execute("SELECT * FROM customers", fetchall=True)
    return render_template("customers.html", customers=data)


if __name__=="__main__":
    app.run(debug=True)