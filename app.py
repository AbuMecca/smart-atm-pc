"""
app.py — the bank's web portal (Flask).

Two pages:
  /        portal.html  — live dashboard: accounts + recent transactions
  /admin   admin.html   — bank staff screen: add / edit / delete cardholders

Plus a few small JSON API routes that those pages poll every 2 seconds:
  GET    /api/accounts
  POST   /api/accounts
  PUT    /api/accounts/<uid>
  DELETE /api/accounts/<uid>
  GET    /api/transactions

Note: this web portal is the BANK STAFF path. The ATM itself never talks to
Flask — it talks to serial_listener.py over the COM port. Both just happen to
read and write the same atm.db file.

Run with:  python app.py     ->  http://localhost:5000
"""

import re
from datetime import datetime

from flask import Flask, jsonify, render_template, request

import database

app = Flask(__name__)

# Re-read the HTML templates whenever they change on disk. Without this Flask
# caches them at startup, so editing a page would appear to do nothing until
# you restarted the server - confusing while working on the screens.
app.config["TEMPLATES_AUTO_RELOAD"] = True

# ---------------------------------------------------------------------------
# Small validation helpers (used by the admin API only)
# ---------------------------------------------------------------------------

UID_PATTERN = re.compile(r"^[0-9A-Fa-f]{4,16}$")   # hex text, e.g. "A1B2C3D4"
NAME_PATTERN = re.compile(r"^[A-Za-z ]{1,30}$")    # letters (and spaces) only
PIN_PATTERN = re.compile(r"^[0-9]{4}$")            # exactly 4 digits


def validate_new_account(uid, name, pin, balance):
    """Check the add-cardholder form. Returns an error string, or None if fine."""
    if not uid or not UID_PATTERN.match(uid):
        return "UID must be 4-16 hex characters (0-9, A-F)."
    if not name or not NAME_PATTERN.match(name):
        return "Name must contain letters only."
    if not pin or not PIN_PATTERN.match(pin):
        return "PIN must be exactly 4 digits."
    try:
        if int(balance) < 0:
            return "Balance cannot be negative."
    except (TypeError, ValueError):
        return "Balance must be a whole number."
    return None


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    """Bank operations dashboard + live ATM monitor.

    The tables are filled in by JavaScript rather than by Jinja, because they
    refresh every second without reloading the page.
    """
    return render_template("dashboard.html")


@app.route("/atm")
def atm_screen():
    """The big ATM screen — a LIVE MIRROR of what the STM32 is showing.

    This page is display only. It has no keypad that does anything and it
    makes no decisions. It polls /api/atm_state four times a second and draws
    whatever screen the board last reported through its ST: messages.

    Put this on the projector full-screen (F11). The customer still uses the
    real card and the real keypad on the STM32.
    """
    return render_template("atm_screen.html")


@app.route("/admin")
def admin():
    """Cardholder management screen for bank staff."""
    return render_template("admin.html")


# ---------------------------------------------------------------------------
# JSON API — accounts
# ---------------------------------------------------------------------------

@app.route("/api/accounts", methods=["GET"])
def api_get_accounts():
    """Every account, for the portal table and the admin table."""
    return jsonify(database.get_all_accounts())


@app.route("/api/accounts", methods=["POST"])
def api_add_account():
    """Add a new cardholder from the admin form."""
    data = request.get_json(silent=True) or {}

    uid = str(data.get("uid", "")).strip().upper()
    name = str(data.get("name", "")).strip()
    pin = str(data.get("pin", "")).strip()
    balance = data.get("balance", 0)

    error = validate_new_account(uid, name, pin, balance)
    if error:
        return jsonify({"ok": False, "error": error}), 400

    if not database.add_account(uid, name, pin, int(balance), 0):
        return jsonify({"ok": False, "error": f"UID {uid} already exists."}), 409

    return jsonify({"ok": True, "account": database.get_account(uid)}), 201


@app.route("/api/accounts/<uid>", methods=["PUT"])
def api_edit_account(uid):
    """Edit an existing cardholder: balance, name, pin and/or lock status.

    Only the fields present in the request body are changed.
    """
    uid = uid.upper()
    if database.get_account(uid) is None:
        return jsonify({"ok": False, "error": f"UID {uid} not found."}), 404

    data = request.get_json(silent=True) or {}
    name = pin = balance = locked = None

    if "name" in data:
        name = str(data["name"]).strip()
        if not NAME_PATTERN.match(name):
            return jsonify({"ok": False, "error": "Name must contain letters only."}), 400

    if "pin" in data:
        pin = str(data["pin"]).strip()
        if not PIN_PATTERN.match(pin):
            return jsonify({"ok": False, "error": "PIN must be exactly 4 digits."}), 400

    if "balance" in data:
        try:
            balance = int(data["balance"])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Balance must be a whole number."}), 400
        if balance < 0:
            return jsonify({"ok": False, "error": "Balance cannot be negative."}), 400

    if "locked" in data:
        locked = 1 if int(data["locked"]) else 0

    if name is None and pin is None and balance is None and locked is None:
        return jsonify({"ok": False, "error": "Nothing to update."}), 400

    database.update_account(uid, name=name, pin=pin, balance=balance, locked=locked)
    return jsonify({"ok": True, "account": database.get_account(uid)})


@app.route("/api/accounts/<uid>", methods=["DELETE"])
def api_delete_account(uid):
    """Remove a cardholder completely."""
    uid = uid.upper()
    if not database.delete_account(uid):
        return jsonify({"ok": False, "error": f"UID {uid} not found."}), 404
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# JSON API — transactions
# ---------------------------------------------------------------------------

@app.route("/api/transactions", methods=["GET"])
def api_get_transactions():
    """Recent transactions, newest first. ?limit=N to change how many."""
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 500))  # keep it sensible
    return jsonify(database.get_transactions(limit))


# ---------------------------------------------------------------------------
# JSON API — the live ATM monitor
# ---------------------------------------------------------------------------

# If nothing has arrived from the STM32 for this long, the customer has
# clearly walked away, so the screen goes back to the attract screen.
# It is generous on purpose: someone reading the menu or thinking about their
# PIN should not have the screen reset underneath them.
IDLE_AFTER_SECONDS = 60


@app.route("/api/atm_state", methods=["GET"])
def api_atm_state():
    """What the ATM appears to be doing right now.

    DISPLAY ONLY. This route just reports the state the serial listener wrote
    down as messages arrived from the board. Nothing here controls the ATM.
    """
    state = database.get_atm_state()
    if state is None:
        return jsonify({"state": "IDLE", "detail": "Idle - waiting for card",
                        "uid": None, "name": None, "amount": 0,
                        "seconds_ago": 0})

    # How long ago was this written? Used both to fade back to idle and to
    # show "3s ago" on the dashboard.
    seconds_ago = 0
    try:
        written = datetime.fromisoformat(state["updated"])
        seconds_ago = max(0, int((datetime.now() - written).total_seconds()))
    except (ValueError, TypeError):
        pass

    # An old event means the customer has gone; show the machine as idle
    # again. We do not rewrite the database here — the dashboard simply
    # displays it as idle, and the real last event stays in the log.
    if seconds_ago > IDLE_AFTER_SECONDS and state["state"] != "IDLE":
        state = dict(state)
        state["state"] = "IDLE"
        state["detail"] = "Idle - waiting for card"
        state["uid"] = None
        state["name"] = None
        state["amount"] = 0

    result = dict(state)
    result["seconds_ago"] = seconds_ago
    return jsonify(result)


if __name__ == "__main__":
    # Make sure the tables exist even if someone forgot to run seed.py.
    database.init_db()
    print("AAST Bank portal running at http://localhost:5000")
    # debug=False so the auto-reloader does not run the file twice.
    app.run(host="0.0.0.0", port=5000, debug=False)
