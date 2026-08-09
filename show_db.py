"""
show_db.py — print the raw contents of atm.db, with no web server involved.

This exists for the demo: it proves the database is a real, separate thing
that stands on its own. The website is just one way of looking at it; the
STM32 is another.

    python show_db.py
"""

import sqlite3

import database


def print_table(title, rows, columns):
    """Print one table as aligned text."""
    print(f"\n{title}")
    print("-" * 74)

    if not rows:
        print("  (empty)")
        return

    # Column width = the widest value in that column, or the header if bigger.
    widths = [
        max(len(str(col)), max(len(str(r[i])) for r in rows))
        for i, col in enumerate(columns)
    ]

    print("  " + "  ".join(str(c).upper().ljust(w) for c, w in zip(columns, widths)))
    print("  " + "  ".join("-" * w for w in widths))
    for row in rows:
        print("  " + "  ".join(str(v).ljust(w) for v, w in zip(row, widths)))


def main():
    print("=" * 74)
    print(" AAST Bank - raw contents of the SQLite database")
    print(f" File: {database.DB_PATH}")
    print("=" * 74)

    conn = sqlite3.connect(database.DB_PATH)

    # --- The schema: what the tables actually look like -------------------
    print("\nSCHEMA (the CREATE TABLE statements SQLite is storing)")
    print("-" * 74)
    for (sql,) in conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ):
        print(sql)
        print()

    # --- The data ----------------------------------------------------------
    cur = conn.execute("SELECT uid, name, pin, balance, locked FROM accounts ORDER BY name")
    print_table("TABLE: accounts", cur.fetchall(),
                ["uid", "name", "pin", "balance", "locked"])

    cur = conn.execute(
        "SELECT id, uid, type, amount, timestamp FROM transactions ORDER BY id DESC"
    )
    print_table("TABLE: transactions (newest first)", cur.fetchall(),
                ["id", "uid", "type", "amount", "timestamp"])

    # --- A couple of totals, to show it is queryable ------------------------
    total = conn.execute("SELECT SUM(balance) FROM accounts").fetchone()[0] or 0
    count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    print("\n" + "-" * 74)
    print(f"  {count} transaction(s) logged.  Total held: EGP {total:,}")

    conn.close()


if __name__ == "__main__":
    main()
