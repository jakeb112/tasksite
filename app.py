from flask import Flask, render_template, request, redirect, url_for
import json, os
import requests
from datetime import datetime

# -----------------------------------------
# CONFIG
# -----------------------------------------
WEBHOOK_URL = "YOUR_WEBHOOK_URL_HERE"   # <<--- PUT YOUR DISCORD WEBHOOK HERE
TASKS_FILE = "tasks.json"

app = Flask(__name__)

# -----------------------------------------
# TASK STORAGE LOGIC
# -----------------------------------------
def load_tasks():
    if not os.path.exists(TASKS_FILE):
        return []
    with open(TASKS_FILE, "r") as f:
        return json.load(f)

def save_tasks(tasks):
    with open(TASKS_FILE, "w") as f:
        json.dump(tasks, f, indent=2)

def get_next_id(tasks):
    if not tasks:
        return 1
    return max(t["id"] for t in tasks) + 1

# -----------------------------------------
# DISCORD EMBED BUILDER
# -----------------------------------------
def build_embed(tasks):
    pending = [t for t in tasks if not t["done"]]
    desc = f"You have **{len(pending)}** pending tasks." if pending else "No pending tasks 🎉"

    fields = []
    for t in pending:
        fields.append({
            "name": f"{t['id']}. {t['title']}",
            "value": t.get("note", ""),
            "inline": False
        })

    embed = {
        "title": "📝 Task List",
        "description": desc,
        "color": 0x00FF99,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

    if fields:
        embed["fields"] = fields

    return embed

# -----------------------------------------
# SEND TO DISCORD
# -----------------------------------------
def send_to_discord():
    tasks = load_tasks()
    embed = build_embed(tasks)
    resp = requests.post(WEBHOOK_URL, json={"embeds": [embed]})

    # Logs visible on Render (helpful for debugging)
    print("Discord status:", resp.status_code)
    print("Discord response:", resp.text)

# -----------------------------------------
# FLASK ROUTES
# -----------------------------------------
@app.route("/")
def index():
    tasks = load_tasks()
    return render_template("index.html", tasks=tasks)

@app.route("/add", methods=["POST"])
def add_task():
    tasks = load_tasks()
    tasks.append({
        "id": get_next_id(tasks),
        "title": request.form["title"],
        "note": request.form.get("note", ""),
        "done": False
    })
    save_tasks(tasks)
    return redirect(url_for("index"))

@app.route("/done/<int:task_id>", methods=["POST"])
def mark_done(task_id):
    tasks = load_tasks()
    for t in tasks:
        if t["id"] == task_id:
            t["done"] = True
    save_tasks(tasks)
    return redirect(url_for("index"))

@app.route("/send", methods=["POST"])
def send_now():
    send_to_discord()
    return redirect(url_for("index"))

# -----------------------------------------
# MAIN (WEBSITE MODE + CRON MODE)
# -----------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="Send tasks to Discord and exit")
    args = parser.parse_args()

    if args.send:
        send_to_discord()
    else:
        app.run()
