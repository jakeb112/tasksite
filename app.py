from flask import Flask, render_template, request, redirect, url_for
import json, os
import requests
from datetime import datetime

WEBHOOK_URL = "https://discord.com/api/webhooks/1448095964660240516/Qu5RKHzKZif4k0aKb8VqR5wNFDtTDnbABgwYjm-zbPx_OCTU50V_D0sv5KRXaxbO81Bb"   # <-- replace this later
TASKS_FILE = "tasks.json"

app = Flask(__name__)

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

def build_embed(tasks):
    pending = [t for t in tasks if not t["done"]]
    desc = f"You have **{len(pending)}** pending tasks." if pending else "No pending tasks 🎉"

    fields = [{
        "name": f"{t['id']}. {t['title']}",
        "value": t.get("note", ""),
        "inline": False
    } for t in pending]

    embed = {
        "title": "📝 Task List",
        "description": desc,
        "color": 0x00FF99,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

    if fields:
        embed["fields"] = fields

    return embed

def send_to_discord():
    tasks = load_tasks()
    embed = build_embed(tasks)
    requests.post(WEBHOOK_URL, json={"embeds": [embed]})

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

if __name__ == "__main__":
    app.run(debug=True)
