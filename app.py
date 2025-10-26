# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import random
from datetime import datetime, timedelta
from pathlib import Path
import os

# ---------- CONFIG ----------
DB = 'users.db'
app = Flask(__name__)
app.secret_key = 'replace_with_a_random_secret_here'  # CHANGE for production
OTP_TTL_SECONDS = 5 * 60  # demo OTP lifetime
ADMIN_PASSWORD = os.environ.get('VOTE_ADMIN_PW', 'adminpass')  # set env var VOTE_ADMIN_PW in production

# ---------- DB init ----------
def init_db():
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            mobile TEXT UNIQUE,
            email TEXT UNIQUE,
            phone_verified INTEGER DEFAULT 0,
            email_verified INTEGER DEFAULT 0,
            otp_code TEXT,
            otp_expires DATETIME
        )
        ''')
        c.execute('''
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            team TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        ''')
        conn.commit()

# ---------- helpers ----------
def generate_otp():
    return f"{random.randint(0, 999999):06d}"

def now_plus(seconds):
    return (datetime.utcnow() + timedelta(seconds=seconds)).isoformat()

def set_otp_for_user_by_mobile(mobile, otp):
    expires = now_plus(OTP_TTL_SECONDS)
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('UPDATE users SET otp_code=?, otp_expires=? WHERE mobile=?', (otp, expires, mobile))
        conn.commit()

def set_otp_for_user_by_email(email, otp):
    expires = now_plus(OTP_TTL_SECONDS)
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('UPDATE users SET otp_code=?, otp_expires=? WHERE email=?', (otp, expires, email))
        conn.commit()

def get_user_by_mobile(mobile):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE mobile=?', (mobile,))
        return c.fetchone()

def get_user_by_email(email):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE email=?', (email,))
        return c.fetchone()

def get_user_by_id(uid):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE id=?', (uid,))
        return c.fetchone()

# ---------- Routes ----------
@app.route('/')
def index():
    return redirect(url_for('register_page'))

# Registration (phone, new user)
@app.route('/register', methods=['GET'])
def register_page():
    return render_template('register.html')

@app.route('/register', methods=['POST'])
def register():
    name = request.form.get('name','').strip()
    mobile = request.form.get('mobile','').strip()
    if not name or not mobile:
        return render_template('register.html', message="Please provide name and mobile")

    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('SELECT id FROM users WHERE mobile=?', (mobile,))
        if c.fetchone():
            return render_template('register.html', message="Mobile already registered. Use email verification to sign in if you are an existing user.")
        c.execute('INSERT INTO users (name,mobile,phone_verified) VALUES (?,?,0)', (name, mobile))
        conn.commit()
    otp = generate_otp()
    set_otp_for_user_by_mobile(mobile, otp)
    session['pending_mobile'] = mobile
    # demo: show OTP on screen; production: send SMS
    return render_template('verify_phone.html', mobile=mobile, otp=otp, message="Demo OTP shown below (in production send via SMS).")

@app.route('/verify_phone', methods=['POST'])
def verify_phone():
    mobile = session.get('pending_mobile') or request.form.get('mobile')
    code = request.form.get('otp','').strip()
    if not mobile or not code:
        return render_template('verify_phone.html', mobile=mobile, message="Missing mobile or OTP")

    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('SELECT id, otp_code, otp_expires FROM users WHERE mobile=?', (mobile,))
        row = c.fetchone()
        if not row:
            return render_template('verify_phone.html', mobile=mobile, message="No registration found for this mobile.")
        user_id, otp_code, otp_expires = row
        if not otp_code:
            return render_template('verify_phone.html', mobile=mobile, message="No OTP generated. Register again.")
        if datetime.fromisoformat(otp_expires) < datetime.utcnow():
            return render_template('verify_phone.html', mobile=mobile, message="OTP expired. Register again.")
        if code != otp_code:
            return render_template('verify_phone.html', mobile=mobile, message="Invalid OTP.")
        c.execute('UPDATE users SET phone_verified=1, otp_code=NULL, otp_expires=NULL WHERE id=?', (user_id,))
        conn.commit()

    # mark user logged in
    session.pop('pending_mobile', None)
    session['user_id'] = user_id
    flash('Phone verified and logged in.')
    return redirect(url_for('vote'))

# Email login (existing users)
@app.route('/email_login', methods=['GET','POST'])
def email_login():
    if request.method == 'GET':
        return render_template('email_login.html')
    email = request.form.get('email','').strip()
    if not email:
        return render_template('email_login.html', message="Enter email")
    user = get_user_by_email(email)
    if not user:
        return render_template('email_login.html', message="No account found for that email. Register by phone first or attach email to your account.")
    otp = generate_otp()
    set_otp_for_user_by_email(email, otp)
    session['pending_email'] = email
    return render_template('verify_email.html', email=email, otp=otp, message="Demo OTP shown (in production email it).")

@app.route('/verify_email', methods=['POST'])
def verify_email():
    email = session.get('pending_email') or request.form.get('email')
    code = request.form.get('otp','').strip()
    if not email or not code:
        return render_template('verify_email.html', email=email, message="Missing email or OTP")
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('SELECT id, otp_code, otp_expires FROM users WHERE email=?', (email,))
        row = c.fetchone()
        if not row:
            return render_template('verify_email.html', email=email, message="No pending verification")
        user_id, otp_code, otp_expires = row
        if not otp_code:
            return render_template('verify_email.html', email=email, message="No OTP generated.")
        if datetime.fromisoformat(otp_expires) < datetime.utcnow():
            return render_template('verify_email.html', email=email, message="OTP expired")
        if code != otp_code:
            return render_template('verify_email.html', email=email, message="Invalid OTP")
        c.execute('UPDATE users SET email_verified=1, otp_code=NULL, otp_expires=NULL WHERE id=?', (user_id,))
        conn.commit()
    session.pop('pending_email', None)
    session['user_id'] = user_id
    flash('Email verified and logged in.')
    return redirect(url_for('vote'))

# attach email utility (demo)
@app.route('/set_email', methods=['GET','POST'])
def set_email():
    if request.method == 'GET':
        return render_template('set_email.html')
    mobile = request.form.get('mobile','').strip()
    email = request.form.get('email','').strip()
    if not mobile or not email:
        return render_template('set_email.html', message="Provide both")
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('SELECT id FROM users WHERE mobile=?', (mobile,))
        r = c.fetchone()
        if not r:
            return render_template('set_email.html', message="No user with that mobile")
        try:
            c.execute('UPDATE users SET email=? WHERE mobile=?', (email, mobile))
            conn.commit()
        except sqlite3.IntegrityError:
            return render_template('set_email.html', message="Email already used")
    return redirect(url_for('users'))

# ---------- Voting ----------
@app.route('/vote', methods=['GET','POST'])
def vote():
    user_id = session.get('user_id')
    if not user_id:
        flash('Please login or register first.')
        return redirect(url_for('index'))
    user = get_user_by_id(user_id)
    if not user:
        flash('User not found.')
        return redirect(url_for('index'))
    # only allow users who have verified phone or email to vote
    if not (user['phone_verified'] or user['email_verified']):
        flash('Please verify phone or email before voting.')
        return redirect(url_for('index'))

    TEAMS = ['Team A', 'Team B', 'Team C']  # change to your teams
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('SELECT team FROM votes WHERE user_id=?', (user_id,))
        existing = c.fetchone()

        if request.method == 'POST':
            if existing:
                return render_template('vote.html', user=user, message="You have already voted.", voted=existing[0], teams=TEAMS)
            chosen = request.form.get('team')
            if not chosen or chosen not in TEAMS:
                return render_template('vote.html', user=user, message="Select a valid team.", teams=TEAMS)
            c.execute('INSERT INTO votes (user_id, team) VALUES (?,?)', (user_id, chosen))
            conn.commit()
            return render_template('vote.html', user=user, message="Thanks — your vote was recorded.", voted=chosen, teams=TEAMS)

    return render_template('vote.html', user=user, teams=TEAMS, voted=(existing[0] if existing else None))

# ---------- Admin ----------
@app.route('/admin', methods=['GET','POST'])
def admin():
    if request.method == 'GET':
        # if already admin in session, redirect to dashboard
        if session.get('is_admin'):
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html')
    # POST: log in admin
    pw = request.form.get('password','')
    if pw == ADMIN_PASSWORD:
        session['is_admin'] = True
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_login.html', message="Bad password")

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('is_admin'):
        flash('Admin login required.')
        return redirect(url_for('admin'))
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        # aggregated counts per team
        c.execute('SELECT team, COUNT(*) AS cnt FROM votes GROUP BY team ORDER BY cnt DESC')
        counts = c.fetchall()
        # full list of votes with user info
        c.execute('''
            SELECT v.id as vote_id, v.team, v.created_at, u.id as user_id, u.name, u.mobile, u.email
            FROM votes v JOIN users u ON v.user_id = u.id
            ORDER BY v.created_at DESC
        ''')
        votes = c.fetchall()
    return render_template('admin_dashboard.html', counts=counts, votes=votes)

@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    flash('Admin logged out.')
    return redirect(url_for('admin'))

# ---------- Users view (print) ----------
@app.route('/users')
def users():
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT id,name,mobile,email,phone_verified,email_verified FROM users ORDER BY id DESC')
        rows = c.fetchall()
    return render_template('users.html', users=rows)

# ---------- Logout for normal users ----------
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Logged out.')
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=False, host='0.0.0.0', port=5000)