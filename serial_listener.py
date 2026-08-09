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
  python serial_listener.py            # try the real COM port; if it will not
                                       # open, drop into keyboard mode
  python serial_listener.py --manual   # keyboard mode straight away (no hardware)
  python serial_listener.py --port COM7
"""

import sys

import database

# ---------------------------------------------------------------------------
# CHANGE THIS to match your board.
#   Windows: "COM3", "COM4", ...        Linux/Mac: "/dev/ttyUSB0", "/dev/ttyACM0"
# ---------------------------------------------------------------------------
SERIAL_PORT = "COM3"
BAUD_RATE = 9600          # 8N1 is pyserial's default, so we only set the speed
READ_TIMEOUT = 1          # seconds; lets us notice Ctrl+C between lines

# Transaction types we accept in a TXN message.
MONEY_TYPES = ("WDR", "DEP")


def log(direction, text):
    """Print everything that crosses the wire, so the demo is easy to debug."""
    print(f"  {direction} {text}", flush=True)


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
                return "NONE"             # unknown card is NONE, not ERR
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
            database.set_balance(uid, new_balance)
            database.add_transaction(uid, txn_type, amount)
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

            database.set_pin(uid, new_pin)
            database.add_transaction(uid, "PIN", 0)
            return "OK"

        # --- LOCK:<uid> -----------------------------------------------------
        if command == "LOCK":
            if len(parts) != 2:
                return "ERR"
            uid = parts[1].upper()
            if database.get_account(uid) is None:
                return "ERR"

            database.lock_account(uid)
            database.add_transaction(uid, "LOCK", 0)
            return "OK"

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
# Mode 2: keyboard (no hardware needed)
# ---------------------------------------------------------------------------

def run_manual():
    """Type request lines by hand and see the reply. Same handle_line() runs."""
    print("=" * 62)
    print(" MANUAL MODE - type requests as if you were the STM32")
    print("=" * 62)
    print(" Try these:")
    print("   GET:A1B2C3D4")
    print("   TXN:A1B2C3D4:WDR:500:1500")
    print("   TXN:A1B2C3D4:DEP:200:1700")
    print("   PIN:A1B2C3D4:4321")
    print("   LOCK:11223344")
    print("   GET:FFFFFFFF          (unknown card -> NONE)")
    print(" Type 'quit' to exit.\n")

    while True:
        try:
            request = input("STM32> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nStopped by user.")
            return

        if request.lower() in ("quit", "exit"):
            print("Bye.")
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

    print("=" * 62)
    print(" AAST Bank - Smart ATM serial listener")
    print(" The STM32 decides; this PC only stores and reports.")
    print("=" * 62)

    if "--manual" in args:
        run_manual()
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
