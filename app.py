from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash 
import sqlite3, random, datetime, os

app = Flask(__name__)
app.secret_key = "ANY_RANDOM_SECRET_KEY"

# ---------------- DATABASE CONNECTION ----------------
def get_db():
    conn = sqlite3.connect("polling.db")
    conn.row_factory = sqlite3.Row
    return conn

# ---------------- HOME PAGE ----------------
@app.route("/", strict_slashes=False)
def home():
    return render_template("home.html")

# ---------------- ADMIN LOGIN ----------------
@app.route("/admin", methods=["GET", "POST"], strict_slashes=False)
def admin_login():
    if request.method == "POST":
        name = request.form["name"].strip()
        phone = request.form["phone"].strip()
        if not phone.startswith("91"):
            phone = "91" + phone

        conn = get_db()
        admin = conn.execute("SELECT * FROM admins WHERE name=? AND phone=?", (name, phone)).fetchone()
        conn.close()

        if admin:
            session["admin"] = name
            return redirect(url_for("admin_dashboard"))
        else:
            flash("❌ Invalid admin credentials!", "error")
    return render_template("admin_login.html")

# ---------------- ADMIN DASHBOARD ----------------
@app.route("/admin/dashboard", methods=["GET", "POST"], strict_slashes=False)
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    conn = get_db()

    # --- Create new poll ---
    if request.method == "POST":
        question = request.form["question"].strip()
        options = [opt.strip() for opt in request.form["options"].split(",") if opt.strip()]
        if not question or len(options) < 2:
            flash("❌ Enter question and at least 2 options.", "error")
        else:
            conn.execute("UPDATE polls SET active=0")
            conn.execute(
                "INSERT INTO polls (question, active, created_at) VALUES (?, 1, ?)",
                (question, datetime.datetime.now().isoformat()),
            )
            poll_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            for opt in options:
                conn.execute("INSERT INTO poll_options (poll_id, option_text) VALUES (?, ?)", (poll_id, opt))
            conn.commit()
            flash("✅ Poll created successfully!", "success")
            return redirect(url_for("results"))

    # --- Get data for dashboard ---
    active = conn.execute("SELECT * FROM polls WHERE active=1 LIMIT 1").fetchone()
    voters_data = []
    vote_summary = {}
    if active:
        poll_id = active["id"]
        voters_data = conn.execute("""
            SELECT users.name AS voter, poll_options.option_text AS choice
            FROM votes
            JOIN users ON votes.phone = users.phone
            JOIN poll_options ON votes.option_id = poll_options.id
            WHERE votes.poll_id = ?
        """, (poll_id,)).fetchall()
        # summarize by option
        options = conn.execute("SELECT * FROM poll_options WHERE poll_id=?", (poll_id,)).fetchall()
        for opt in options:
            count = conn.execute("SELECT COUNT(*) FROM votes WHERE option_id=?", (opt["id"],)).fetchone()[0]
            vote_summary[opt["option_text"]] = count

    pending = conn.execute("SELECT * FROM admin_requests WHERE status='pending' ORDER BY created_at").fetchall()
    conn.close()

    voters = [(row["voter"], row["choice"]) for row in voters_data]

    return render_template(
        "admin_dashboard.html",
        active=active,
        pending_requests=pending,
        voters=voters,
        vote_summary=vote_summary
    )

# ---------------- USER REGISTRATION ----------------
@app.route("/user", methods=["GET", "POST"], strict_slashes=False)
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        phone = request.form["phone"].strip()
        if not phone.startswith("91"):
            phone = "91" + phone

        # directly mark verified (no OTP)
        session["phone"] = phone
        session["user_name"] = name

        conn = get_db()
        conn.execute("INSERT OR IGNORE INTO users (phone, name, verified) VALUES (?, ?, 1)", (phone, name))
        conn.commit()
        conn.close()

        flash("✅ Logged in successfully!", "success")
        return redirect(url_for("user_dashboard"))

    return render_template("register.html")

# ---------------- USER DASHBOARD (updated) ----------------
@app.route("/user_dashboard", strict_slashes=False)
def user_dashboard():
    phone = session.get("phone")
    if not phone:
        return redirect(url_for("register"))

    conn = get_db()
    poll = conn.execute("SELECT * FROM polls WHERE active=1 LIMIT 1").fetchone()
    if not poll:
        conn.close()
        flash("❌ No active poll available.", "info")
        return render_template("user_dashboard.html", poll=None)

    options = conn.execute("SELECT * FROM poll_options WHERE poll_id=?", (poll["id"],)).fetchall()
    already = conn.execute("SELECT * FROM votes WHERE phone=? AND poll_id=?", (phone, poll["id"])).fetchone()

    # ✅ NEW: if already voted, show warning page instead of poll
    if already:
        conn.close()
        flash("⚠️ You have already voted! Redirecting to live results.", "info")
        return render_template("already_voted.html")

    total_votes = conn.execute("SELECT COUNT(*) FROM votes WHERE poll_id=?", (poll["id"],)).fetchone()[0]
    option_data = []
    for opt in options:
        count = conn.execute("SELECT COUNT(*) FROM votes WHERE option_id=?", (opt["id"],)).fetchone()[0]
        percentage = round((count / total_votes * 100), 1) if total_votes > 0 else 0
        option_data.append({"id": opt["id"], "option_text": opt["option_text"], "percentage": percentage})

    conn.close()

    return render_template("vote.html", poll=poll, options=option_data, already_voted=False)

# ---------------- VOTE (updated) ----------------
@app.route("/vote", methods=["POST"], strict_slashes=False)
def vote():
    phone = session.get("phone")
    if not phone:
        return redirect(url_for("register"))

    poll_id = request.form.get("poll_id")
    option_id = request.form.get("option")

    conn = get_db()
    already = conn.execute("SELECT * FROM votes WHERE phone=? AND poll_id=?", (phone, poll_id)).fetchone()
    
    # ✅ NEW: Prevent revoting and show redirect message
    if already:
        conn.close()
        flash("⚠️ You have already voted! Redirecting to live results.", "info")
        return render_template("already_voted.html")

    conn.execute("INSERT INTO votes (phone, poll_id, option_id) VALUES (?, ?, ?)", (phone, poll_id, option_id))
    conn.commit()
    conn.close()
    flash("✅ Your vote has been recorded successfully!", "success")
    return redirect(url_for("results"))

# ---------------- RESULTS ----------------
@app.route("/results_json", strict_slashes=False)
def results_json():
    conn = get_db()
    poll = conn.execute("SELECT * FROM polls WHERE active=1 LIMIT 1").fetchone()
    if not poll:
        conn.close()
        return jsonify({"active": False})

    poll_id = poll["id"]
    options = conn.execute("SELECT id, option_text FROM poll_options WHERE poll_id=?", (poll_id,)).fetchall()
    data = []
    for opt in options:
        votes = conn.execute("SELECT COUNT(*) FROM votes WHERE option_id=?", (opt["id"],)).fetchone()[0]
        data.append({"text": opt["option_text"], "votes": votes})

    conn.close()
    return jsonify({"active": True, "question": poll["question"], "options": data})

@app.route("/results", strict_slashes=False)
def results():
    return render_template("results.html")

# ---------------- ADMIN VOTE STATS ----------------
@app.route("/admin/vote_stats", strict_slashes=False)
def vote_stats():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    conn = get_db()
    data = conn.execute("""
        SELECT users.name AS user_name, poll_options.option_text AS choice
        FROM votes
        JOIN users ON votes.phone = users.phone
        JOIN poll_options ON votes.option_id = poll_options.id
    """).fetchall()
    conn.close()

    names = [row["user_name"] for row in data]
    choices = [row["choice"] for row in data]
    return render_template("vote_stats.html", names=names, choices=choices)

# ---------------- INITIALIZE DATABASE ----------------
def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            phone TEXT PRIMARY KEY,
            name TEXT,
            verified INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS polls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT,
            active INTEGER DEFAULT 0,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS poll_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            poll_id INTEGER,
            option_text TEXT
        );
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT,
            poll_id INTEGER,
            option_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS admin_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT UNIQUE,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            processed_at TEXT
        );
    """)
    cur.execute("INSERT OR IGNORE INTO admins (name, phone) VALUES (?, ?)", ("Simran Arya", "918279731664"))
    cur.execute("INSERT OR IGNORE INTO admins (name, phone) VALUES (?, ?)", ("Khyati", "919368472156"))
    conn.commit()
    conn.close()

# ---------------- RUN APP ----------------
if __name__ == "__main__":
    if not os.path.exists("polling.db"):
        init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)













