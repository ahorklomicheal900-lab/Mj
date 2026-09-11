"""Alcantara Daily Sales Desk - production-ready Flask application.

Storage:
- PostgreSQL when DATABASE_URL is supplied (recommended on Render).
- SQLite locally when DATABASE_URL is not supplied.

The existing HTML templates/API contract are intentionally kept compatible.
"""
import html
import os
from datetime import date, datetime
from functools import wraps

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Date, DateTime, Float, Integer, String, Text, create_engine, func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "daily-till-dev-secret")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[len("postgres://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[len("postgresql://"):]

# Render's ephemeral filesystem is not suitable for shop records, so use its
# PostgreSQL database in production. SQLite remains convenient for local use.
if DATABASE_URL:
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
else:
    sqlite_path = os.environ.get("SQLITE_PATH", os.path.join(os.path.dirname(__file__), "shopnexa_sales.db"))
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + sqlite_path

db = SQLAlchemy(app)

ROLE_RANK = {"employee": 1, "manager": 2, "owner": 3}


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(Integer, primary_key=True)
    username = db.Column(String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(String(255), nullable=False)
    role = db.Column(String(20), nullable=False, default="employee")
    display_name = db.Column(String(120), nullable=False)
    created_at = db.Column(DateTime, nullable=False, default=datetime.utcnow)


class Sale(db.Model):
    __tablename__ = "sales"
    id = db.Column(Integer, primary_key=True)
    sale_date = db.Column(Date, nullable=False, default=date.today, index=True)
    item = db.Column(String(255), nullable=False)
    unit_price = db.Column(Float, nullable=False)
    cost_price = db.Column(Float, nullable=False, default=0.0)
    quantity = db.Column(Integer, nullable=False)
    line_total = db.Column(Float, nullable=False)
    profit = db.Column(Float, nullable=False)
    created_at = db.Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    username = db.Column(String(80), nullable=True, index=True)


class LoginLog(db.Model):
    __tablename__ = "login_logs"
    id = db.Column(Integer, primary_key=True)
    username = db.Column(String(80), nullable=False)
    role = db.Column(String(20), nullable=True)
    logged_at = db.Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    success = db.Column(db.Boolean, nullable=False, default=False)
    ip = db.Column(String(64), nullable=True)


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"
    id = db.Column(Integer, primary_key=True)
    username = db.Column(String(80), nullable=False)
    display_name = db.Column(String(120), nullable=False)
    role = db.Column(String(20), nullable=True)
    action = db.Column(Text, nullable=False)
    logged_at = db.Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class ShopSetting(db.Model):
    __tablename__ = "shop_settings"
    key = db.Column(String(80), primary_key=True)
    value = db.Column(Text, nullable=False)


def setting_value(key, default):
    row = db.session.get(ShopSetting, key)
    return row.value if row else default


def get_settings():
    return {
        "shop_name": setting_value("shop_name", "Alcantara Daily Sales Desk"),
        "currency": setting_value("currency", "GHS"),
    }


def set_setting(key, value):
    row = db.session.get(ShopSetting, key)
    if row:
        row.value = value
    else:
        db.session.add(ShopSetting(key=key, value=value))


def bootstrap_database():
    """Create tables and seed an initial owner only when the database is empty."""
    db.create_all()
    if User.query.count() == 0:
        owner_username = os.environ.get("INITIAL_OWNER_USERNAME", "alcantara").strip()
        owner_password = os.environ.get("INITIAL_OWNER_PASSWORD", "backstage123")
        db.session.add(User(
            username=owner_username,
            password_hash=generate_password_hash(owner_password),
            role="owner",
            display_name=os.environ.get("INITIAL_OWNER_DISPLAY_NAME", "Alcantara"),
        ))
        # Optional starter accounts for easy local use. They are NOT created if
        # the database already contains any users.
        if os.environ.get("SEED_DEMO_USERS", "1") == "1":
            db.session.add(User(username="employee", password_hash=generate_password_hash("staff123"), role="employee", display_name="Store Assistant"))
            db.session.add(User(username="manager", password_hash=generate_password_hash("sales123"), role="manager", display_name="Shop Manager"))
    if ShopSetting.query.count() == 0:
        set_setting("shop_name", "Alcantara Daily Sales Desk")
        set_setting("currency", "GHS")
    db.session.commit()


with app.app_context():
    bootstrap_database()


def current_user():
    username = session.get("username")
    user = User.query.filter_by(username=username).first() if username else None
    if user:
        return username, user
    return None, None


def user_dict(user):
    return {
        "password_hash": user.password_hash,
        "role": user.role,
        "display_name": user.display_name,
    }


def serialize_sale(sale):
    return {
        "item": sale.item,
        "unit_price": round(sale.unit_price, 2),
        "cost_price": round(sale.cost_price, 2),
        "quantity": sale.quantity,
        "line_total": round(sale.line_total, 2),
        "profit": round(sale.profit, 2),
        "time": sale.created_at.strftime("%H:%M:%S"),
    }


def today_sales():
    return Sale.query.filter_by(sale_date=date.today()).order_by(Sale.created_at.asc(), Sale.id.asc()).all()


def compute_summary(sales=None):
    sales = today_sales() if sales is None else sales
    total_sales = sum(s.unit_price * s.quantity for s in sales)
    total_units = sum(s.quantity for s in sales)
    total_profit = sum(s.profit for s in sales)
    item_units = {}
    for s in sales:
        item_units[s.item] = item_units.get(s.item, 0) + s.quantity
    best_selling_item = max(item_units, key=item_units.get) if item_units else None
    status = "profit" if total_profit > 0 else ("loss" if total_profit < 0 else "even")
    return {
        "total_sales": round(total_sales, 2),
        "num_transactions": len(sales),
        "total_units": total_units,
        "best_selling_item": best_selling_item,
        "total_profit": round(total_profit, 2),
        "profit_status": status,
    }


def log_activity(action):
    username, user = current_user()
    if not username:
        return
    db.session.add(ActivityLog(
        username=username,
        display_name=user.display_name,
        role=user.role,
        action=action,
    ))
    db.session.commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        username, user = current_user()
        if not username:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Not logged in"}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def owner_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        username, user = current_user()
        if not username:
            return redirect(url_for("login"))
        if user.role != "owner":
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped


def manager_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        username, user = current_user()
        if not username:
            return redirect(url_for("login"))
        if ROLE_RANK.get(user.role, 0) < ROLE_RANK["manager"]:
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        success = bool(user and check_password_hash(user.password_hash, password))
        db.session.add(LoginLog(
            username=username or "(blank)",
            role=user.role if (success and user) else None,
            success=success,
            ip=request.headers.get("X-Forwarded-For", request.remote_addr),
        ))
        db.session.commit()
        if success:
            session.clear()
            session["username"] = username
            return redirect(url_for("index"))
        error = "Incorrect username or password."
    return render_template("login.html", error=error, settings=get_settings())


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    username, user = current_user()
    error = None
    success = None
    if request.method == "POST":
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        confirm_pw = request.form.get("confirm_password", "")
        if not check_password_hash(user.password_hash, current_pw):
            error = "Your current password is incorrect."
        elif len(new_pw) < 6:
            error = "New password must be at least 6 characters."
        elif new_pw != confirm_pw:
            error = "New password and confirmation don't match."
        else:
            user.password_hash = generate_password_hash(new_pw)
            db.session.commit()
            log_activity("Changed their own password")
            success = "Password updated. Use it next time you sign in."
    return render_template("change_password.html", error=error, success=success, user=user_dict(user), settings=get_settings())


@app.route("/backstage")
@owner_required
def backstage():
    users = {u.username: user_dict(u) for u in User.query.order_by(User.username).all()}
    recent_logins = [{"username": x.username, "role": x.role, "time": x.logged_at.strftime("%Y-%m-%d %H:%M:%S"), "success": x.success, "ip": x.ip} for x in LoginLog.query.order_by(LoginLog.logged_at.desc()).limit(50)]
    recent_activity = [{"username": x.username, "display_name": x.display_name, "role": x.role, "action": x.action, "time": x.logged_at.strftime("%Y-%m-%d %H:%M:%S")} for x in ActivityLog.query.order_by(ActivityLog.logged_at.desc()).limit(50)]
    return render_template("backstage.html", users=users, recent_logins=recent_logins, recent_activity=recent_activity, settings=get_settings(), current_username=session.get("username"), error=request.args.get("error"), success=request.args.get("success"))


@app.route("/backstage/add-user", methods=["POST"])
@owner_required
def backstage_add_user():
    username = request.form.get("new_username", "").strip()
    password = request.form.get("new_password", "")
    role = request.form.get("new_role", "manager")
    display_name = request.form.get("new_display_name", "").strip() or username
    if not username or not password:
        return redirect(url_for("backstage", error="Username and password are required."))
    if User.query.filter_by(username=username).first():
        return redirect(url_for("backstage", error=f"'{username}' already exists."))
    if len(password) < 6:
        return redirect(url_for("backstage", error="Password must be at least 6 characters."))
    if role not in ROLE_RANK:
        role = "employee"
    db.session.add(User(username=username, password_hash=generate_password_hash(password), role=role, display_name=display_name))
    db.session.commit()
    log_activity(f"Added staff account '{username}' as {role}")
    return redirect(url_for("backstage", success=f"Added '{username}' as {role}."))


@app.route("/backstage/update-role", methods=["POST"])
@owner_required
def backstage_update_role():
    username = request.form.get("username", "")
    new_role = request.form.get("role", "")
    current = session.get("username")
    user = User.query.filter_by(username=username).first()
    if not user:
        return redirect(url_for("backstage", error="That user doesn't exist."))
    if new_role not in ROLE_RANK:
        return redirect(url_for("backstage", error="Not a valid role."))
    if username == current and new_role != "owner":
        return redirect(url_for("backstage", error="You can't demote the account you're signed in with."))
    if user.role == "owner" and new_role != "owner" and User.query.filter_by(role="owner").count() <= 1:
        return redirect(url_for("backstage", error="Can't demote the last owner account."))
    old_role = user.role
    user.role = new_role
    db.session.commit()
    log_activity(f"Changed '{username}' role from {old_role} to {new_role}")
    return redirect(url_for("backstage", success=f"'{username}' is now {new_role}."))


@app.route("/backstage/remove-user", methods=["POST"])
@owner_required
def backstage_remove_user():
    username = request.form.get("username", "")
    current = session.get("username")
    user = User.query.filter_by(username=username).first()
    if username == current:
        return redirect(url_for("backstage", error="You can't remove the account you're signed in with."))
    if not user:
        return redirect(url_for("backstage", error="That user doesn't exist."))
    if user.role == "owner" and User.query.filter_by(role="owner").count() <= 1:
        return redirect(url_for("backstage", error="Can't remove the last owner account."))
    db.session.delete(user)
    db.session.commit()
    log_activity(f"Removed staff account '{username}'")
    return redirect(url_for("backstage", success=f"Removed '{username}'."))


@app.route("/backstage/settings", methods=["POST"])
@owner_required
def backstage_settings():
    shop_name = request.form.get("shop_name", "").strip()
    currency = request.form.get("currency", "").strip()
    if shop_name:
        set_setting("shop_name", shop_name[:120])
    if currency:
        set_setting("currency", currency[:12])
    db.session.commit()
    log_activity("Updated shop settings")
    return redirect(url_for("backstage", success="Settings updated."))


@app.route("/team")
@manager_required
def team_dashboard():
    employees = {u.username: user_dict(u) for u in User.query.filter_by(role="employee").order_by(User.username).all()}
    recent_logins = LoginLog.query.filter(LoginLog.role != "owner").order_by(LoginLog.logged_at.desc()).limit(50).all()
    recent_activity = ActivityLog.query.filter(ActivityLog.role != "owner").order_by(ActivityLog.logged_at.desc()).limit(50).all()
    login_rows = [{"username": x.username, "role": x.role, "time": x.logged_at.strftime("%Y-%m-%d %H:%M:%S"), "success": x.success, "ip": x.ip} for x in recent_logins]
    activity_rows = [{"username": x.username, "display_name": x.display_name, "role": x.role, "action": x.action, "time": x.logged_at.strftime("%Y-%m-%d %H:%M:%S")} for x in recent_activity]
    return render_template("team.html", employees=employees, recent_logins=login_rows, recent_activity=activity_rows, settings=get_settings(), current_username=session.get("username"), error=request.args.get("error"), success=request.args.get("success"))


@app.route("/team/add-employee", methods=["POST"])
@manager_required
def team_add_employee():
    username = request.form.get("new_username", "").strip()
    password = request.form.get("new_password", "")
    display_name = request.form.get("new_display_name", "").strip() or username
    if not username or not password:
        return redirect(url_for("team_dashboard", error="Username and password are required."))
    if User.query.filter_by(username=username).first():
        return redirect(url_for("team_dashboard", error=f"'{username}' already exists."))
    if len(password) < 6:
        return redirect(url_for("team_dashboard", error="Password must be at least 6 characters."))
    db.session.add(User(username=username, password_hash=generate_password_hash(password), role="employee", display_name=display_name))
    db.session.commit()
    log_activity(f"Added employee account '{username}'")
    return redirect(url_for("team_dashboard", success=f"Added '{username}' to the team."))


@app.route("/team/remove-employee", methods=["POST"])
@manager_required
def team_remove_employee():
    username = request.form.get("username", "")
    user = User.query.filter_by(username=username).first()
    if not user:
        return redirect(url_for("team_dashboard", error="That user doesn't exist."))
    if user.role != "employee":
        return redirect(url_for("team_dashboard", error="You can only remove employee accounts from here."))
    db.session.delete(user)
    db.session.commit()
    log_activity(f"Removed employee account '{username}'")
    return redirect(url_for("team_dashboard", success=f"Removed '{username}'."))


@app.route("/")
@login_required
def index():
    username, user = current_user()
    return render_template("index.html", user=user_dict(user), settings=get_settings())


@app.route("/api/sale", methods=["POST"])
@login_required
def add_sale():
    data = request.get_json(silent=True) or {}
    item = str(data.get("item", "")).strip()
    try:
        unit_price = float(data.get("unit_price"))
        quantity = int(data.get("quantity"))
        cost_price = float(data.get("cost_price") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Prices must be numbers and quantity must be a whole number"}), 400
    if not item:
        return jsonify({"error": "Item name is required"}), 400
    if unit_price <= 0:
        return jsonify({"error": "Unit price must be greater than 0"}), 400
    if quantity <= 0:
        return jsonify({"error": "Quantity must be greater than 0"}), 400
    if cost_price < 0:
        return jsonify({"error": "Cost price can't be negative"}), 400
    _, user = current_user()
    sale = Sale(
        sale_date=date.today(), item=item[:255], unit_price=round(unit_price, 2), cost_price=round(cost_price, 2),
        quantity=quantity, line_total=round(unit_price * quantity, 2), profit=round((unit_price - cost_price) * quantity, 2),
        username=user.username,
    )
    db.session.add(sale)
    db.session.commit()
    log_activity(f"Recorded sale: {item} x{quantity}")
    sales = today_sales()
    return jsonify({"summary": compute_summary(sales), "transactions": [serialize_sale(s) for s in sales]}), 201


@app.route("/api/summary")
@login_required
def get_summary():
    sales = today_sales()
    return jsonify({"summary": compute_summary(sales), "transactions": [serialize_sale(s) for s in sales]})


@app.route("/api/reset", methods=["POST"])
@login_required
def reset():
    sales = today_sales()
    count = len(sales)
    for sale in sales:
        db.session.delete(sale)
    db.session.commit()
    log_activity(f"Reset the day's transactions ({count} cleared)")
    return jsonify({"summary": compute_summary([]), "transactions": []})


@app.route("/api/report")
@login_required
def report():
    sales = today_sales()
    summary = compute_summary(sales)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = get_settings()
    currency = html.escape(settings["currency"])
    shop_name = html.escape(settings["shop_name"])
    rows = []
    for t in sales:
        profit = t.profit
        rows.append(
            f"<tr><td>{t.created_at.strftime('%H:%M:%S')}</td><td>{html.escape(t.item)}</td>"
            f"<td>{t.unit_price:.2f}</td><td>{t.quantity}</td><td>{t.line_total:.2f}</td><td>{profit:+.2f}</td></tr>"
        )
    rows_html = "".join(rows) or "<tr><td colspan='6' style='text-align:center;'>No transactions recorded</td></tr>"
    profit_word = {"profit": "In profit", "loss": "Operating at a loss", "even": "Break even"}[summary["profit_status"]]
    html_doc = f"""<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'><title>{shop_name} — Sales Report</title>
<style>body{{font-family:Arial,sans-serif;margin:0;padding:2.5rem;color:#e8e4da;background:#05070a}}h1{{color:#f5efe3}}.meta{{color:#8a8478}}.summary{{display:flex;flex-wrap:wrap;gap:1rem;margin-bottom:2rem}}.box{{background:#12181a;border:1px solid rgba(245,239,227,.08);border-radius:10px;padding:1rem 1.25rem;min-width:150px}}.label{{text-transform:uppercase;font-size:.68rem;color:#a89f8c}}.value{{font-size:1.3rem;font-weight:700;color:#f0a63e}}table{{border-collapse:collapse;width:100%;background:#0d1214}}th,td{{padding:10px 14px;text-align:left;border-bottom:1px solid rgba(245,239,227,.06)}}th{{background:#12181a;color:#a89f8c}}</style></head><body>
<p>Daily Snapshot</p><h1>{shop_name} — Sales Report</h1><p class='meta'>Generated {generated_at}</p><div class='summary'>
<div class='box'><div class='label'>Total sales</div><div class='value'>{currency} {summary['total_sales']:.2f}</div></div>
<div class='box'><div class='label'>Transactions</div><div class='value'>{summary['num_transactions']}</div></div>
<div class='box'><div class='label'>Units sold</div><div class='value'>{summary['total_units']}</div></div>
<div class='box'><div class='label'>Best seller</div><div class='value'>{html.escape(summary['best_selling_item'] or 'N/A')}</div></div>
<div class='box'><div class='label'>{profit_word}</div><div class='value'>{currency} {summary['total_profit']:+.2f}</div></div></div>
<table><thead><tr><th>Time</th><th>Item</th><th>Unit Price</th><th>Qty</th><th>Line Total</th><th>Profit</th></tr></thead><tbody>{rows_html}</tbody></table></body></html>"""
    log_activity("Downloaded the sales report")
    return Response(html_doc, mimetype="text/html", headers={"Content-Disposition": "attachment; filename=sales_report.html"})


@app.get("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify({"status": "ok", "database": "connected"})
    except Exception:
        db.session.rollback()
        return jsonify({"status": "error", "database": "unavailable"}), 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=os.environ.get("FLASK_DEBUG") == "1")
