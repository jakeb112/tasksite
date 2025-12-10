import os
from datetime import datetime

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

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "YOUR_WEBHOOK_HERE")
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

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tasks = db.relationship("Task", backref="user", lazy=True)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    note = db.Column(db.Text)
    done = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


# -----------------------------------------
# LOGIN MANAGER
# -----------------------------------------

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# -----------------------------------------
# DISCORD
# -----------------------------------------

def build_embed(tasks):
    """Build Discord embed from a list of Task objects."""
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
        "title": "📝 Task List",
        "description": desc,
        "color": 0x00FF99,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    if fields:
        embed["fields"] = fields

    return embed


def send_to_discord(for_user: User | None = None):
    """Send pending tasks to Discord. If for_user is given, only their tasks."""
    if not WEBHOOK_URL or "discord" not in WEBHOOK_URL:
        print("WEBHOOK_URL not set or invalid, skipping Discord send")
        return

    with app.app_context():
        if for_user is None:
            tasks = Task.query.filter_by(done=False).order_by(Task.id).all()
        else:
            tasks = (
                Task.query.filter_by(user_id=for_user.id, done=False)
                .order_by(Task.id)
                .all()
            )

        embed = build_embed(tasks)
        payload = {"embeds": [embed]}

        try:
            resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
            print("Discord status:", resp.status_code)
            print("Discord response:", resp.text)
            resp.raise_for_status()
        except Exception as e:
            print("Error sending to Discord:", repr(e))


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
    # send only current user's tasks
    send_to_discord(for_user=current_user)
    flash("Tasks sent to Discord.", "success")
    return redirect(url_for("index"))


# -----------------------------------------
# DB INIT ROUTE (simple hacky migration)
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
        help="Send all pending tasks to Discord and exit (cron mode).",
    )
    args = parser.parse_args()

    if args.send:
        # In CLI/cron mode we send *all* users' tasks
        send_to_discord(for_user=None)
    else:
        app.run(debug=True)