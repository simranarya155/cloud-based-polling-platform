import sqlite3

conn = sqlite3.connect('polling.db')
cur = conn.cursor()

# ✅ Table for polls
cur.execute('''
CREATE TABLE IF NOT EXISTS polls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    option1 TEXT,
    option2 TEXT,
    option3 TEXT,
    option4 TEXT,
    votes1 INTEGER DEFAULT 0,
    votes2 INTEGER DEFAULT 0,
    votes3 INTEGER DEFAULT 0,
    votes4 INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1
)
''')

# ✅ Table for tracking user votes by phone number
cur.execute('''
CREATE TABLE IF NOT EXISTS votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL UNIQUE,
    poll_id INTEGER NOT NULL,
    selected_option INTEGER NOT NULL,
    FOREIGN KEY (poll_id) REFERENCES polls (id)
)
''')

conn.commit()
conn.close()

print("✅ Database initialized successfully with polls and votes tables!")

