"""
database.py — all SQLite access for the Smart ATM project.

Everything that touches atm.db lives here, so app.py (the web portal) and
serial_listener.py (the STM32 link) never write raw SQL themselves.

Remember the golden rule of this project: the PC is only storage.
No PIN checking, no "do they have enough money?" checks happen here.
The STM32 decides; we just save what it tells us.
"""

import os
import sqlite3
from datetime import datetime

# The database file sits next to this script, so it does not matter which
# folder you launch python from.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "atm.db")


def get_connection():
    """Open a connection to atm.db.

    row_factory = sqlite3.Row lets us read columns by name (row["name"])
    instead of by number (row[1]), which is much easier to read.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the two tables if they do not exist yet. Safe to run twice."""
    conn = get_connection()
    cur = conn.cursor()

    # One row per RFID card / cardholder.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            uid     TEXT PRIMARY KEY,   -- RFID card UID as hex text, e.g. "A1B2C3D4"
            name    TEXT NOT NULL,      -- cardholder name, letters only
            pin     TEXT NOT NULL,      -- 4 digits kept as text so "0000" stays "0000"
            balance INTEGER NOT NULL,   -- whole EGP only, no decimals
            locked  INTEGER NOT NULL    -- 0 = open, 1 = locked
        )
        """
    )

    # One row per event: withdrawal, deposit, PIN change or card lock.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            uid       TEXT NOT NULL,
            type      TEXT NOT NULL,    -- "WDR", "DEP", "PIN" or "LOCK"
            amount    INTEGER,          -- 0 or NULL for non-money events
            timestamp TEXT NOT NULL     -- ISO datetime string
        )
        """
    )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def get_account(uid):
    """Return one account as a dict, or None if that card is unknown."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM accounts WHERE uid = ?", (uid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_accounts():
    """Return every account as a list of dicts, sorted by name."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM accounts ORDER BY name ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_account(uid, name, pin, balance, locked=0):
    """Insert a new cardholder. Returns True, or False if the uid already exists."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO accounts (uid, name, pin, balance, locked) VALUES (?, ?, ?, ?, ?)",
            (uid, name, pin, int(balance), int(locked)),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Happens when the uid is already in the table (PRIMARY KEY clash).
        return False
    finally:
        conn.close()


def update_account(uid, name=None, pin=None, balance=None, locked=None):
    """Update only the fields that were actually passed in.

    Example: update_account("A1B2C3D4", balance=5000) changes just the balance.
    Returns True if a row was changed, False if the uid does not exist.
    """
    fields = []   # the "column = ?" pieces of the SQL
    values = []   # the matching values

    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if pin is not None:
        fields.append("pin = ?")
        values.append(pin)
    if balance is not None:
        fields.append("balance = ?")
        values.append(int(balance))
    if locked is not None:
        fields.append("locked = ?")
        values.append(int(locked))

    if not fields:
        return False  # nothing to do

    values.append(uid)  # the value for the WHERE clause
    sql = "UPDATE accounts SET " + ", ".join(fields) + " WHERE uid = ?"

    conn = get_connection()
    cur = conn.execute(sql, values)
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def delete_account(uid):
    """Remove a cardholder. Returns True if a row was actually deleted."""
    conn = get_connection()
    cur = conn.execute("DELETE FROM accounts WHERE uid = ?", (uid,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def set_balance(uid, new_balance):
    """Store the balance the STM32 already calculated. No maths on this side."""
    return update_account(uid, balance=new_balance)


def lock_account(uid):
    """Set locked = 1 (used by the LOCK serial command)."""
    return update_account(uid, locked=1)


def set_pin(uid, new_pin):
    """Store a new PIN (used by the PIN serial command)."""
    return update_account(uid, pin=new_pin)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def add_transaction(uid, txn_type, amount=0):
    """Write one line into the transaction log with the current time."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    conn = get_connection()
    conn.execute(
        "INSERT INTO transactions (uid, type, amount, timestamp) VALUES (?, ?, ?, ?)",
        (uid, txn_type, amount, timestamp),
    )
    conn.commit()
    conn.close()


def get_transactions(limit=50):
    """Return the most recent transactions, newest first.

    We join on accounts so the portal can show the cardholder's name too.
    LEFT JOIN means a transaction still shows up even if the account was
    later deleted by the admin.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT t.id, t.uid, t.type, t.amount, t.timestamp, a.name
        FROM transactions t
        LEFT JOIN accounts a ON a.uid = t.uid
        ORDER BY t.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
