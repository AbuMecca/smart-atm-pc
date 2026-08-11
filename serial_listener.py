"""
serial_listener.py — the UART link between the STM32 ATM panel and this PC.

THE GOLDEN RULE OF THIS FILE:
    The STM32 makes every decision. This script only stores data and answers
    questions. There is no PIN checking and no "enough money?" checking here.
    If the STM32 says the new balance is 500, we write 500 — even if that
    looks wrong. That is intentional.

Port settings: 9600 baud, 8 data bits, no parity, 1 stop bit (8N1).
Messages are plain ASCII, fields separated by ':', each line ends with '\n'.
The STM32 always asks first; we send back exactly ONE line. We never speak
unprompted.

Protocol
--------
  GET:<uid>                              -> REC:<name>:<pin>:<balance>:<locked>
                                            or NONE if the card is unknown
  TXN:<uid>:<type>:<amount>:<newbalance> -> OK / ERR
  PIN:<uid>:<newpin>                     -> OK / ERR
  LOCK:<uid>                             -> OK / ERR

How to run
----------
  py serial_listener.py --listen    # BANK MODE (no hardware): wait for a
                                    # PC-based ATM (atm_gui.py) to connect.
                                    # This is what 1_BANK.bat uses.
  py serial_listener.py             # REAL HARDWARE: open the COM port below.
                                    # Falls back to keyboard mode if it fails.
  py serial_listener.py --manual    # keyboard mode: type protocol lines by hand
  py serial_listener.py --port COM7 # override the COM port for one run

Whichever mode is used, the rules never change: one request in, exactly one
response out, and the PC never speaks first.
"""

import queue
import socket
import sys
import threading
import time

import database

# ---------------------------------------------------------------------------
# CHANGE THIS to match your board.
#   Windows: "COM3", "COM4", ...        Linux/Mac: "/dev/ttyUSB0", "/dev/ttyACM0"
# ---------------------------------------------------------------------------
SERIAL_PORT = "COM5"
BAUD_RATE = 9600          # 8N1 is pyserial's default, so we only set the speed
READ_TIMEOUT = 1          # seconds; lets us notice Ctrl+C between lines

# Port used by --listen mode, where PC-based ATMs connect instead of a cable.
# Must match BANK_PORT in fake_stm32.py.
LISTEN_PORT = 5555

# Transaction types we accept in a TXN message.
MONEY_TYPES = ("WDR", "DEP")


def log(direction, text):
    """Print everything that crosses the wire, so the demo is easy to debug."""
    print(f"  {direction} {text}", flush=True)


# Some screens announce a RESULT and are replaced by the next message almost
# straight away — the board says "dispensing", then goes back to its menu a
# moment later. Without a minimum display time the money screen flashes past
# before the audience can read it. These are the screens worth holding, and
# for how many seconds.
HOLD_SECONDS = {
    "DISPENSE":   3.0,   # the money shot of the demo
    "TXN_WDR":    3.0,   # same thing, inferred from a TXN when there is no ST:
    "DEPOSIT":    3.0,
    "TXN_DEP":    3.0,
    "LOCKED":     3.0,
    "PINCHANGED": 2.5,
    "PIN_CHANGED": 2.5,
    "THANKS":     2.5,
}


# The screen updates are written on a BACKGROUND thread.
#
# Why: mirror() writes a row to the database, and a database write can, in bad
# luck, wait for a lock (another program such as DB Browser holding the file).
# If that happened while we were part-way through answering a GET, the STM32
# would be left waiting for its REC line and would decide the PC had gone
# away. Screen bookkeeping must never be able to delay a reply to the board.
#
# So mirror() only drops the update into a queue - which takes microseconds -
# and this worker writes it a moment later.
_mirror_jobs = queue.Queue()
_mirror_thread = None


def _mirror_worker():
    """Write queued screen updates, one at a time, off the reply path."""
    while True:
        job = _mirror_jobs.get()
        try:
            database.set_atm_state(*job)
        except Exception as err:
            print(f"  !! could not update the screen: {err}", flush=True)
        finally:
            _mirror_jobs.task_done()


def _ensure_mirror_worker():
    global _mirror_thread
    if _mirror_thread is None:
        _mirror_thread = threading.Thread(target=_mirror_worker, daemon=True)
        _mirror_thread.start()


def mirror_flush(timeout=3.0):
    """Wait for queued screen updates to reach the database.

    Only needed when the program is about to exit — for example after piping
    a file of test commands into manual mode — so the last screen is not lost
    when the background thread is killed on shutdown.
    """
    deadline = time.time() + timeout
    while not _mirror_jobs.empty() and time.time() < deadline:
        time.sleep(0.02)
    time.sleep(0.05)          # let any in-flight write finish


def mirror(state, detail, uid=None, name=None, amount=0):
    """Tell the dashboard what the ATM appears to be doing.

    This ONLY feeds the "Live ATM Monitor" panel on the website. It never
    changes the reply we send back to the STM32, and it never decides
    anything. If this function failed completely, the ATM would still work
    exactly the same — which is why the whole call is wrapped in try/except.

    We work the state out from the messages the board already sends, so the
    protocol stays exactly as it was: a GET means a card was tapped, a
    TXN:WDR means cash is being dispensed, a LOCK means the card was blocked.
    """
    _ensure_mirror_worker()
    _mirror_jobs.put((state, detail, uid, name, amount,
                      HOLD_SECONDS.get(state, 0)))


# ---------------------------------------------------------------------------
# ST: status messages — the STM32 telling the big screen what it is showing
# ---------------------------------------------------------------------------

def handle_status(parts):
    """Record one ST: status message so the /atm mirror screen can show it.

    parts is the already-split message, e.g. ["ST", "DISPENSE", "500"].

    These messages are ONE-WAY. Nothing is sent back to the board, and nothing
    here changes an account. If this function did nothing at all, the ATM
    would still work perfectly — the screen would just stop updating.

    A note on names: cardholder names are letters and spaces only, so a name
    can never contain a ':'. We still re-join the tail with ':' rather than
    taking parts[2], so an unexpected value can never silently lose data.
    """
    screen = parts[1].upper() if len(parts) > 1 else ""
    value = ":".join(parts[2:]) if len(parts) > 2 else ""

    # Screens that carry a person's name.
    if screen in ("WELCOME", "MENU"):
        mirror(screen, f"{screen.title()} - {value}", name=value)
        return

    # Screens that carry a number (money, tries left, or how many PIN dots).
    if screen in ("BALANCE", "DISPENSE", "DEPOSIT", "WRONGPIN", "PINDOTS"):
        try:
            number = int(value)
        except ValueError:
            number = 0

        if screen == "PINDOTS":
            # Not a screen change: the customer is still on the PIN screen,
            # they have just pressed another key. Keep the state as PIN and
            # only move the dot count, so the screen does not flicker.
            state = database.get_atm_state() or {}
            mirror("PIN", "Enter your PIN",
                   uid=state.get("uid"), name=state.get("name"),
                   amount=max(0, min(number, 4)))
            return

        wording = {
            "BALANCE":  f"Balance shown: EGP {number:,}",
            "DISPENSE": f"Dispensing EGP {number:,}",
            "DEPOSIT":  f"Deposit received: EGP {number:,}",
            "WRONGPIN": f"Wrong PIN - {number} tries left",
        }[screen]
        mirror(screen, wording, amount=number)
        return

    # Screens that carry nothing at all.
    plain = {
        "IDLE":       "Idle - waiting for card",
        "PIN":        "Enter your PIN",
        "LOCKED":     "Card locked",
        "PINCHANGED": "PIN changed successfully",
        "THANKS":     "Thank you - please take your card",
    }
    if screen in plain:
        # Starting PIN entry resets the dots back to zero.
        mirror(screen, plain[screen])
        return

    # Unknown ST: message. Log it and carry on; never crash the listener.
    print(f"  ?? unknown status message: ST:{screen}", flush=True)


# ---------------------------------------------------------------------------
# The protocol itself
# ---------------------------------------------------------------------------

def handle_line(line):
    """Turn one request line into exactly one response string.

    This function is deliberately separate from the serial reading loop, so the
    exact same logic runs whether the line came from the STM32, from a virtual
    COM port, or from the keyboard. It never raises: any unexpected problem
    becomes "ERR".
    """
    # lstrip("﻿") drops a byte-order-mark, which Windows text files
    # sometimes put at the very start when you pipe a script of test commands in.
    line = line.strip().lstrip("﻿")
    if not line:
        return None                       # blank line: nothing to answer

    parts = line.split(":")
    command = parts[0].upper()

    try:
        # --- GET:<uid> -----------------------------------------------------
        if command == "GET":
            if len(parts) != 2:
                return "ERR"
            uid = parts[1].upper()
            account = database.get_account(uid)

            if account is None:
                # Unknown card is NONE, not ERR.
                mirror("UNKNOWN_CARD", f"Unknown card {uid} - refused", uid=uid)
                return "NONE"

            if account["locked"]:
                mirror("CARD_BLOCKED",
                       f"Blocked card presented: {account['name']}",
                       uid=uid, name=account["name"])
            else:
                # A GET means a card was just tapped on the reader. The STM32
                # will now ask the customer for a PIN.
                mirror("CARD_READ",
                       f"Card inserted: {account['name']} - awaiting PIN",
                       uid=uid, name=account["name"])

            return (f"REC:{account['name']}:{account['pin']}:"
                    f"{account['balance']}:{account['locked']}")

        # --- TXN:<uid>:<type>:<amount>:<newbalance> ------------------------
        if command == "TXN":
            if len(parts) != 5:
                return "ERR"
            uid = parts[1].upper()
            txn_type = parts[2].upper()
            amount = int(parts[3])
            new_balance = int(parts[4])

            if txn_type not in MONEY_TYPES:
                return "ERR"
            if database.get_account(uid) is None:
                return "ERR"

            # Store the balance the STM32 already worked out. No maths here.
            account = database.get_account(uid)
            database.set_balance(uid, new_balance)
            database.add_transaction(uid, txn_type, amount)

            # A TXN can only happen after the STM32 accepted the PIN, so the
            # monitor can safely show this as an authorised customer.
            if txn_type == "WDR":
                mirror("TXN_WDR", f"Dispensing EGP {amount:,}",
                       uid=uid, name=account["name"], amount=amount)
            else:
                mirror("TXN_DEP", f"Accepting deposit of EGP {amount:,}",
                       uid=uid, name=account["name"], amount=amount)
            return "OK"

        # --- PIN:<uid>:<newpin> --------------------------------------------
        if command == "PIN":
            if len(parts) != 3:
                return "ERR"
            uid = parts[1].upper()
            new_pin = parts[2]
            if len(new_pin) != 4 or not new_pin.isdigit():
                return "ERR"
            if database.get_account(uid) is None:
                return "ERR"

            account = database.get_account(uid)
            database.set_pin(uid, new_pin)
            database.add_transaction(uid, "PIN", 0)
            mirror("PIN_CHANGED", f"PIN changed for {account['name']}",
                   uid=uid, name=account["name"])
            return "OK"

        # --- LOCK:<uid> -----------------------------------------------------
        if command == "LOCK":
            if len(parts) != 2:
                return "ERR"
            uid = parts[1].upper()
            if database.get_account(uid) is None:
                return "ERR"

            account = database.get_account(uid)
            database.lock_account(uid)
            database.add_transaction(uid, "LOCK", 0)
            mirror("LOCKED", f"Card locked: {account['name']}",
                   uid=uid, name=account["name"])
            return "OK"

        # --- ST:<screen>[:<value>] -----------------------------------------
        # ONE-WAY STATUS MESSAGES.
        #
        # These are not requests and they are NOT part of the request/response
        # contract above. The STM32 shouts them out as it moves through its
        # own flow, purely so the big PC screen can mirror what the little
        # 16x2 LCD is showing. We record the state and return None, which
        # means "say nothing back" - the board is not waiting for a reply.
        if command == "ST":
            handle_status(parts)
            return None

        # Anything else is not part of the contract.
        return "ERR"

    except ValueError:
        # int() failed, e.g. "TXN:A1B2C3D4:WDR:abc:100"
        print("  !! bad number in request", flush=True)
        return "ERR"
    except Exception as err:
        # A database write failed, or something else unexpected.
        # We log it and answer ERR rather than crashing the listener.
        print(f"  !! error handling line: {err}", flush=True)
        return "ERR"


# ---------------------------------------------------------------------------
# Mode 1: real serial port
# ---------------------------------------------------------------------------

def run_serial(port):
    """Open the COM port and answer requests forever."""
    import serial   # imported here so keyboard mode works even without pyserial

    print(f"Opening {port} at {BAUD_RATE} baud (8N1)...")
    # serial_for_url() behaves exactly like serial.Serial() for a normal port
    # name such as "COM3" or "/dev/ttyUSB0". The bonus is that it also accepts
    # "socket://localhost:5555", which is how fake_stm32.py lets us test this
    # very same code path with no hardware and no drivers installed.
    link = serial.serial_for_url(
        port,
        baudrate=BAUD_RATE,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=READ_TIMEOUT,
    )
    print(f"Listening on {port}. Press Ctrl+C to stop.\n")

    try:
        while True:
            # readline() waits for '\n' or gives up after READ_TIMEOUT.
            raw = link.readline()
            if not raw:
                continue                      # timeout, just loop again

            # errors="replace" means stray bytes never crash the decode.
            request = raw.decode("ascii", errors="replace").strip()
            if not request:
                continue

            log("RX <-", request)
            response = handle_line(request)
            if response is None:
                continue

            log("TX ->", response)
            link.write((response + "\n").encode("ascii"))
            link.flush()

    except KeyboardInterrupt:
        print("\nStopped by user.")
    except serial.SerialException as err:
        # The port went away in the middle of the session: the board was
        # unplugged, or the fake STM32 on the other end quit.
        print(f"\nConnection to {port} lost: {err}")
    finally:
        link.close()
        print(f"{port} closed.")


# ---------------------------------------------------------------------------
# Mode 2: the bank waits for PC-based ATMs to connect (no hardware needed)
# ---------------------------------------------------------------------------

def serve_one_atm(conn, address):
    """Talk to one connected ATM until it disconnects.

    Exactly the same rules as the serial loop: read one request line, answer
    with exactly one response line, never speak first.
    """
    print(f"\nATM connected from {address[0]}:{address[1]}\n", flush=True)
    buffer = b""

    while True:
        # Collect bytes until we have a complete '\n'-terminated line.
        while b"\n" not in buffer:
            try:
                chunk = conn.recv(256)
            except OSError:
                return
            if not chunk:
                return                      # the ATM hung up
            buffer += chunk

        raw, buffer = buffer.split(b"\n", 1)
        request = raw.decode("ascii", errors="replace").strip()
        if not request:
            continue

        log("RX <-", request)
        response = handle_line(request)
        if response is None:
            continue

        log("TX ->", response)
        try:
            conn.sendall((response + "\n").encode("ascii"))
        except OSError:
            return                          # the ATM vanished mid-reply


def run_listen(port):
    """Act as the bank: sit on a port and serve whichever ATM connects.

    When an ATM closes, we simply wait for the next one, so the bank can stay
    running all day while cash machines come and go.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        # Windows: stop a second copy of the bank silently stealing the port.
        server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        # 127.0.0.1 (not "localhost") so the ATM always finds us on IPv4,
        # and so the bank is reachable only from this PC.
        server.bind(("127.0.0.1", port))
    except OSError as err:
        print(f"\nCould not open port {port}: {err}")
        print("Another bank is probably already running. Close it and retry.\n")
        server.close()
        return

    server.listen(1)
    print(f"Bank is open on port {port}. Waiting for an ATM to connect...")
    print("Start the ATM now (2_ATM.bat). Press Ctrl+C to close the bank.\n")

    try:
        while True:
            conn, address = server.accept()
            try:
                serve_one_atm(conn, address)
            finally:
                conn.close()
            mirror("IDLE", "Idle - waiting for card")
            print("\nATM disconnected. Waiting for the next one...\n", flush=True)
    except KeyboardInterrupt:
        print("\nBank closed by user.")
    finally:
        server.close()


# ---------------------------------------------------------------------------
# Mode 3: keyboard (no hardware needed)
# ---------------------------------------------------------------------------

def run_manual():
    """Type request lines by hand and see the reply. Same handle_line() runs."""
    print("=" * 62)
    print(" MANUAL MODE - type requests as if you were the STM32")
    print("=" * 62)
    print(" DATA requests (the PC answers each one):")
    print("   GET:A1B2C3D4")
    print("   TXN:A1B2C3D4:WDR:500:1500")
    print("   TXN:A1B2C3D4:DEP:200:1700")
    print("   PIN:A1B2C3D4:4321")
    print("   LOCK:11223344")
    print("   GET:FFFFFFFF          (unknown card -> NONE)")
    print()
    print(" SCREEN messages (one-way; drive the /atm mirror, no reply sent):")
    print("   ST:IDLE            ST:PIN             ST:PINDOTS:3")
    print("   ST:WELCOME:Amro    ST:MENU:Amro       ST:BALANCE:2000")
    print("   ST:DISPENSE:500    ST:DEPOSIT:200     ST:WRONGPIN:2")
    print("   ST:LOCKED          ST:PINCHANGED      ST:THANKS")
    print()
    print(" Watch http://localhost:5000/atm while you type these.")
    print(" Type 'quit' to exit.\n")

    while True:
        try:
            request = input("STM32> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nStopped by user.")
            mirror_flush()          # let the last screen update land
            return

        if request.lower() in ("quit", "exit"):
            print("Bye.")
            mirror_flush()
            return
        if not request:
            continue

        log("RX <-", request)
        response = handle_line(request)
        if response is not None:
            log("TX ->", response)


# ---------------------------------------------------------------------------
# Start-up
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]

    # --port COMx overrides the constant at the top of the file.
    port = SERIAL_PORT
    if "--port" in args:
        port = args[args.index("--port") + 1]

    database.init_db()   # make sure the tables exist
    mirror("IDLE", "Idle - waiting for card")   # reset the dashboard monitor

    print("=" * 62)
    print(" AAST Bank - Smart ATM serial listener")
    print(" The STM32 decides; this PC only stores and reports.")
    print("=" * 62)

    if "--manual" in args:
        run_manual()
        return

    # --listen: no hardware. Wait for a PC-based ATM (atm_gui.py / atm_sim.py)
    # to connect. This is what 1_BANK.bat uses.
    if "--listen" in args:
        index = args.index("--listen")
        # An optional port may follow, e.g. --listen 5556
        if index + 1 < len(args) and args[index + 1].isdigit():
            run_listen(int(args[index + 1]))
        else:
            run_listen(LISTEN_PORT)
        return

    try:
        run_serial(port)
    except ImportError:
        print("pyserial is not installed. Run: pip install -r requirements.txt")
        print("Falling back to manual mode.\n")
        run_manual()
    except Exception as err:
        # Almost always "port does not exist" / "access denied" on Windows.
        print(f"Could not open {port}: {err}")
        print("No hardware? Falling back to manual mode.\n")
        run_manual()


if __name__ == "__main__":
    main()
