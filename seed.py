"""
seed.py — creates atm.db and fills it with a few sample cardholders.

Run this once before starting the portal:

    python seed.py

Running it again just tops the sample accounts back up; it will not create
duplicates (the uid is the primary key).
"""

import database

# The three demo cards from the project brief.
SAMPLE_ACCOUNTS = [
    # (uid,        name,    pin,    balance, locked)
    ("A1B2C3D4", "Amro",  "1234", 2000, 0),
    ("11223344", "Anas",  "4321", 500,  0),
    ("DEADBEEF", "Guest", "0000", 100,  1),
]


def main():
    # 1. Make sure the tables exist.
    database.init_db()
    print(f"Database ready at: {database.DB_PATH}")

    # 2. Insert each sample account (skipping any that are already there).
    for uid, name, pin, balance, locked in SAMPLE_ACCOUNTS:
        if database.add_account(uid, name, pin, balance, locked):
            print(f"  added   {uid}  {name}")
        else:
            print(f"  exists  {uid}  {name}  (left unchanged)")

    # 3. Show what is in the table now, as a quick confirmation.
    print("\nAccounts currently in atm.db:")
    print(f"{'UID':<12}{'NAME':<10}{'PIN':<6}{'BALANCE':>9}  STATUS")
    for acc in database.get_all_accounts():
        status = "LOCKED" if acc["locked"] else "Open"
        print(
            f"{acc['uid']:<12}{acc['name']:<10}{acc['pin']:<6}"
            f"{acc['balance']:>9}  {status}"
        )


if __name__ == "__main__":
    main()
