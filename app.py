import os
from datetime import datetime, timedelta

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    login_user,
    login_required,
    logout_user,
    current_user,
    UserMixin,
)
from werkzeug.security import generate_password_hash, check_password_hash
import requests


# -----------------------------------------
# CONFIG
# -----------------------------------------

def _normalize_db_url(url: str) -> str:
    """Render gives postgres://, SQLAlchemy wants postgresql://"""
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


DATABASE_URL = _normalize_db_url(
    os.environ.get("DATABASE_URL", "sqlite:///local.db")
)

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"


# -----------------------------------------
# MODELS
# -----------------------------------------

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # Per-user Discord + schedule
    webhook_url = db.Column(db.String(300))          # user's own webhook
    ping_interval_hours = db.Column(db.Integer, default=0)  # 0 = disabled
    last_ping_at = db.Column(db.DateTime, nullable=True)    # when we last auto-pinged

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tasks = db.relationship("Task", backref="user", lazy=True)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    note = db.Column(db.Text)
    done = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)


# -----------------------------------------
# LOGIN MANAGER
# -----------------------------------------

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# -----------------------------------------
# DISCORD
# -----------------------------------------

def build_embed_for_user(user, tasks):
    """Build a Discord embed for a single user's tasks."""
    pending = [t for t in tasks if not t.done]
    if pending:
        desc = f"You have **{len(pending)}** pending task(s)."
    else:
        desc = "No pending tasks 🎉"

    fields = []
    for t in pending:
        note = t.note or "No extra info"
        fields.append(
            {
                "name": f"{t.id}. {t.title}",
                "value": note,
                "inline": False,
            }
        )

    embed = {
        "title": f"📝 Tasks for {user.email}",
        "description": desc,
        "color": 0x00FF99,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    if fields:
        embed["fields"] = fields

    return embed


def send_to_discord_for_user(user: User):
    """Send one user's pending tasks to their own webhook (ignores schedule)."""
    webhook_url = user.webhook_url
    if not webhook_url:
        print(f"User {user.email} has no webhook set, skipping.")
        return

    with app.app_context():
        tasks = (
            Task.query.filter_by(user_id=user.id, done=False)
            .order_by(Task.id)
            .all()
        )

    if not tasks:
        print(f"User {user.email} has no pending tasks, skipping.")
        return

    embed = build_embed_for_user(user, tasks)
    payload = {"embeds": [embed]}

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        print(f"[{user.email}] Discord status:", resp.status_code)
        print(f"[{user.email}] Discord response:", resp.text)
        resp.raise_for_status()
    except Exception as e:
        print(f"Error sending to Discord for {user.email}:", repr(e))


def should_ping_user(user: User, now: datetime) -> bool:
    """
    Decide if cron should ping this user now based on:
    - webhook set
    - ping_interval_hours
    - last_ping_at
    """
    if not user.webhook_url:
        return False

    interval = user.ping_interval_hours or 0
    if interval <= 0:
        # 0 or negative = disabled
        return False

    if user.last_ping_at is None:
        # never pinged before -> ping
        return True

    return (now - user.last_ping_at) >= timedelta(hours=interval)


def send_to_discord_all_users():
    """Cron mode: send for all users who are due based on their interval."""
    now = datetime.utcnow()
    with app.app_context():
        users = User.query.all()
        for user in users:
            if should_ping_user(user, now):
                send_to_discord_for_user(user)
                user.last_ping_at = now  # update last ping time
        db.session.commit()


# -----------------------------------------
# ROUTES: AUTH
# -----------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not email or not password:
            flash("Email and password are required.", "error")
            return redirect(url_for("register"))

        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for("register"))

        existing = User.query.filter_by(email=email).first()
        if existing:
            flash("That email is already registered.", "error")
            return redirect(url_for("register"))

        user = User(email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash("Account created. You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid email or password.", "error")
            return redirect(url_for("login"))

        login_user(user)
        flash("Logged in successfully.", "success")
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# -----------------------------------------
# ROUTES: SETTINGS (WEBHOOK + INTERVAL)
# -----------------------------------------

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        webhook = request.form.get("webhook", "").strip()
        interval_raw = request.form.get("ping_interval_hours", "0").strip()

        try:
            interval = int(interval_raw)
        except ValueError:
            interval = 0

        # clamp 0–24
        if interval < 0:
            interval = 0
        if interval > 24:
            interval = 24

        current_user.webhook_url = webhook or None
        current_user.ping_interval_hours = interval
        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("settings"))

    return render_template("settings.html", user=current_user)


# -----------------------------------------
# ROUTES: TASKS
# -----------------------------------------

@app.route("/")
@login_required
def index():
    tasks = (
        Task.query.filter_by(user_id=current_user.id)
        .order_by(Task.id.desc())
        .all()
    )
    return render_template("index.html", tasks=tasks)


@app.route("/add", methods=["POST"])
@login_required
def add_task():
    title = request.form.get("title", "").strip()
    note = request.form.get("note", "").strip()

    if not title:
        flash("Task title is required.", "error")
        return redirect(url_for("index"))

    task = Task(title=title, note=note, user_id=current_user.id)
    db.session.add(task)
    db.session.commit()

    flash("Task added.", "success")
    return redirect(url_for("index"))


@app.route("/done/<int:task_id>", methods=["POST"])
@login_required
def mark_done(task_id):
    task = Task.query.filter_by(id=task_id, user_id=current_user.id).first()
    if not task:
        flash("Task not found.", "error")
        return redirect(url_for("index"))

    task.done = True
    db.session.commit()
    flash("Task marked as done.", "success")
    return redirect(url_for("index"))


@app.route("/send", methods=["POST"])
@login_required
def send_now():
    # Manual send: ignore schedule; just send for this user
    send_to_discord_for_user(current_user)
    flash("Tasks sent to your Discord webhook (if set).", "success")
    return redirect(url_for("index"))


# -----------------------------------------
# DB INIT ROUTE
# -----------------------------------------

@app.route("/init-db")
def init_db():
    """One-time route to create tables. Hit once after deploying/migrating."""
    db.create_all()
    return "Database tables created."


# -----------------------------------------
# MAIN ENTRYPOINT (web vs cron)
# -----------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send due users' pending tasks to their webhooks and exit (cron).",
    )
    args = parser.parse_args()

    if args.send:
        send_to_discord_all_users()
    else:
        app.run(debug=True)
