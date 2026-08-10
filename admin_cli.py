"""
admin_cli.py — the bank staff admin tool, in the terminal.

This is the PRIMARY way bank staff manage cardholders. It reads and writes the
same atm.db file that the web dashboard displays and the serial listener uses,
so anything changed here shows up on the dashboard within a second, and the
STM32 sees it on the card's next GET.

Run it with:

    py admin_cli.py

It is a simple numbered menu — no arguments to remember:

    1  List all accounts
    2  Add a new cardholder
    3  Edit a balance
    4  Lock / unlock a card
    5  Delete a cardholder
    6  Show recent transactions
    0  Quit

NOTE ON SAFETY: this tool is the BANK's side of the system, not the ATM's.
It is allowed to change balances directly because that is what a bank clerk
does. The ATM itself still has no such power — it can only send the four
protocol messages.
"""

import re

import database

# What a valid entry looks like. The same shapes the web admin page enforces.
UID_PATTERN = re.compile(r"^[0-9A-Fa-f]{4,16}$")   # hex text, e.g. "A1B2C3D4"
NAME_PATTERN = re.compile(r"^[A-Za-z ]{1,30}$")    # letters and spaces only
PIN_PATTERN = re.compile(r"^[0-9]{4}$")            # exactly 4 digits


# ===========================================================================
# Small input helpers — they keep asking until the answer is valid,
# and let the user type nothing (just Enter) to back out.
# ===========================================================================

def ask(prompt):
    """Ask for a line of text. Returns None if the user pressed Enter alone."""
    try:
        answer = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return answer or None


def ask_pattern(prompt, pattern, complaint):
    """Ask until the answer matches `pattern`. Enter alone cancels."""
    while True:
        answer = ask(prompt)
        if answer is None:
            return None
        if pattern.match(answer):
            return answer
        print(f"   ! {complaint}")


def ask_whole_number(prompt, allow_zero=True):
    """Ask until the answer is a whole number. Enter alone cancels."""
    while True:
        answer = ask(prompt)
        if answer is None:
            return None
        if answer.isdigit():
            value = int(answer)
            if value == 0 and not allow_zero:
                print("   ! Must be more than zero.")
                continue
            return value
        print("   ! Please type a whole number (no decimals, no minus sign).")


def confirm(prompt):
    """Ask a yes/no question. Anything other than 'y' means no."""
    answer = ask(f"{prompt} (y/N): ")
    return answer is not None and answer.lower().startswith("y")


def ask_existing_uid(prompt):
    """Ask for a card UID that actually exists, and return its account row."""
    uid = ask(prompt)
    if uid is None:
        return None
    account = database.get_account(uid.upper())
    if account is None:
        print(f"   ! No cardholder with UID {uid.upper()}.")
        return None
    return account


# ===========================================================================
# The menu actions
# ===========================================================================

def list_accounts():
    """Print every cardholder as a table."""
    accounts = database.get_all_accounts()
    print()
    if not accounts:
        print("   No cardholders yet. Use option 2 to add one.")
        return

    print(f"   {'UID':<12}{'NAME':<14}{'PIN':<6}{'BALANCE':>10}   STATUS")
    print("   " + "-" * 52)
    total = 0
    for account in accounts:
        status = "LOCKED" if account["locked"] else "Open"
        total += account["balance"]
        print(f"   {account['uid']:<12}{account['name']:<14}{account['pin']:<6}"
              f"{account['balance']:>10,}   {status}")
    print("   " + "-" * 52)
    print(f"   {len(accounts)} account(s), EGP {total:,} held in total.")


def add_account():
    """Issue a new card."""
    print("\n   New cardholder (press Enter alone at any point to cancel)")

    uid = ask_pattern("   Card UID (hex, e.g. A1B2C3D4): ", UID_PATTERN,
                      "UID must be 4-16 hex characters (0-9, A-F).")
    if uid is None:
        return print("   Cancelled.")
    uid = uid.upper()

    if database.get_account(uid) is not None:
        return print(f"   ! UID {uid} already exists. Nothing added.")

    name = ask_pattern("   Cardholder name: ", NAME_PATTERN,
                       "Name must contain letters only.")
    if name is None:
        return print("   Cancelled.")

    pin = ask_pattern("   4-digit PIN: ", PIN_PATTERN,
                      "PIN must be exactly 4 digits.")
    if pin is None:
        return print("   Cancelled.")

    balance = ask_whole_number("   Opening balance (EGP): ")
    if balance is None:
        return print("   Cancelled.")

    if database.add_account(uid, name, pin, balance, 0):
        print(f"   Card {uid} issued to {name} with EGP {balance:,}.")
    else:
        print(f"   ! Could not add {uid}.")


def edit_balance():
    """Correct a balance by hand (a bank clerk action, not an ATM one)."""
    print("\n   Edit a balance (press Enter alone to cancel)")
    account = ask_existing_uid("   Card UID: ")
    if account is None:
        return

    print(f"   {account['name']} currently holds EGP {account['balance']:,}.")
    balance = ask_whole_number("   New balance (EGP): ")
    if balance is None:
        return print("   Cancelled.")

    database.update_account(account["uid"], balance=balance)
    print(f"   {account['name']}'s balance is now EGP {balance:,}.")


def toggle_lock():
    """Lock a card, or reset a lock so the cardholder can use the ATM again."""
    print("\n   Lock / unlock a card (press Enter alone to cancel)")
    account = ask_existing_uid("   Card UID: ")
    if account is None:
        return

    if account["locked"]:
        print(f"   {account['name']}'s card is currently LOCKED.")
        if confirm("   Reset the lock (unlock it)?"):
            database.update_account(account["uid"], locked=0)
            print(f"   {account['name']}'s card is now open.")
        else:
            print("   Left locked.")
    else:
        print(f"   {account['name']}'s card is currently open.")
        if confirm("   Lock it?"):
            database.update_account(account["uid"], locked=1)
            print(f"   {account['name']}'s card is now LOCKED.")
        else:
            print("   Left open.")


def delete_account():
    """Remove a cardholder completely."""
    print("\n   Delete a cardholder (press Enter alone to cancel)")
    account = ask_existing_uid("   Card UID: ")
    if account is None:
        return

    print(f"   This will permanently remove {account['name']} ({account['uid']}) "
          f"holding EGP {account['balance']:,}.")
    if not confirm("   Are you sure?"):
        return print("   Cancelled. Nothing deleted.")

    if database.delete_account(account["uid"]):
        print(f"   {account['name']} deleted.")
        print("   (Their past transactions stay in the log for the audit trail.)")
    else:
        print("   ! Nothing was deleted.")


def show_transactions():
    """Show the most recent activity."""
    count = ask_whole_number("\n   How many to show? (Enter for 20): ")
    transactions = database.get_transactions(count or 20)

    print()
    if not transactions:
        print("   No transactions logged yet.")
        return

    print(f"   {'WHEN':<21}{'TYPE':<6}{'CARD':<12}{'NAME':<12}{'AMOUNT':>10}")
    print("   " + "-" * 61)
    for t in transactions:
        when = t["timestamp"].replace("T", " ")
        amount = f"{t['amount']:,}" if t["type"] in ("WDR", "DEP") else "-"
        print(f"   {when:<21}{t['type']:<6}{t['uid']:<12}"
              f"{(t['name'] or '?'):<12}{amount:>10}")


MENU = """
   +------------------------------------------+
   |  1)  List all accounts                   |
   |  2)  Add a new cardholder                |
   |  3)  Edit a balance                      |
   |  4)  Lock / unlock a card                |
   |  5)  Delete a cardholder                 |
   |  6)  Show recent transactions            |
   |  0)  Quit                                |
   +------------------------------------------+"""

ACTIONS = {
    "1": list_accounts,
    "2": add_account,
    "3": edit_balance,
    "4": toggle_lock,
    "5": delete_account,
    "6": show_transactions,
}


def main():
    # Make sure the tables exist, in case seed.py was never run.
    database.init_db()

    print("=" * 62)
    print(" AAST BANK - CARDHOLDER ADMINISTRATION")
    print(" Bank staff tool. Writes directly to atm.db.")
    print("=" * 62)
    print(f" Database: {database.DB_PATH}")

    while True:
        print(MENU)
        choice = ask("   Choose an option: ")

        if choice is None or choice == "0":
            print("\n   Goodbye.\n")
            return

        action = ACTIONS.get(choice)
        if action is None:
            print(f"   ! '{choice}' is not on the menu.")
            continue

        try:
            action()
        except Exception as err:
            # Never let one bad action kill the whole tool.
            print(f"   ! Something went wrong: {err}")


if __name__ == "__main__":
    main()
