"""
atm_sim.py — a full ATM session simulated on the PC, with no hardware.

    Scan card -> enter PIN -> menu -> withdraw / deposit / change PIN -> eject

This program pretends to be the STM32 ATM panel. It talks to serial_listener.py
over exactly the same UART protocol the real board will use.

WHY THIS FILE MATTERS
---------------------
Every decision an ATM makes is made HERE, not on the PC:

  * Is this card known?          -> decided from the GET reply
  * Is the card blocked?         -> decided from the GET reply
  * Is the PIN correct?          -> compared locally, PC never sees the attempt
  * Three wrong tries?           -> this program decides to send LOCK
  * Enough money to withdraw?    -> checked locally BEFORE anything is sent
  * What is the new balance?     -> calculated here, then sent to the PC

The PC only ever stores what it is told. That split is the whole point of the
project, and this file is the half that will become the STM32 firmware
(Blue Pill / STM32F103 in C). Read it as a specification for that firmware.

HOW TO RUN
----------
  Terminal 1:  python atm_sim.py
  Terminal 2:  python serial_listener.py --port socket://localhost:5555

  Or against a virtual COM pair (com0com / socat):
  Terminal 1:  python atm_sim.py --port COM5
  Terminal 2:  python serial_listener.py --port COM4

Keep http://localhost:5000 open while you use it - the portal updates live.
"""

import sys

# Reuse the connection layer from fake_stm32.py so there is only one copy of
# the socket / COM port code in the project.
from fake_stm32 import connect

# --- ATM policy. These are the bank's rules, enforced by the ATM itself. ---
MAX_PIN_ATTEMPTS = 3        # after this many wrong PINs, the card is locked
NOTE_SIZE = 50              # the machine only holds EGP 50 notes
MAX_WITHDRAWAL = 5000       # per-transaction limit


# ===========================================================================
# Small helpers for the "screen"
# ===========================================================================

def screen(*lines):
    """Print something the cardholder would see on the ATM display."""
    print()
    for line in lines:
        print(f"   | {line}")
    print()


def atm(message):
    """Print a decision the ATM made internally.

    These lines are the interesting ones during the demo: they show the board
    thinking, with no message going to the bank.
    """
    print(f"  [ATM] {message}")


def ask(prompt):
    """Read one line of input. Returns None if the user wants out."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None


# ===========================================================================
# Talking to the bank
# ===========================================================================

class Bank:
    """One request, one response — with the traffic printed for the demo."""

    def __init__(self, send_line, read_line):
        self._send = send_line
        self._read = read_line

    def request(self, message):
        """Send one line, return the one line that comes back (or None)."""
        print(f"  TX -> {message}")
        self._send(message)
        reply = self._read()
        if reply is None:
            print("  !! the bank did not answer (is serial_listener.py running?)")
            return None
        print(f"  RX <- {reply}")
        return reply


# ===========================================================================
# The card record we get back from GET
# ===========================================================================

class Card:
    """Whatever the bank knows about the card now in the slot.

    The STM32 will hold this in a struct while the customer is served, and
    update `balance` locally after each accepted transaction, so it only needs
    one GET per session.
    """

    def __init__(self, uid, name, pin, balance, locked):
        self.uid = uid
        self.name = name
        self.pin = pin
        self.balance = balance
        self.locked = locked

    @staticmethod
    def parse(uid, reply):
        """Turn 'REC:Amro:1234:2000:0' into a Card, or None if it is not a REC."""
        parts = reply.split(":")
        if len(parts) != 5 or parts[0] != "REC":
            return None
        return Card(uid, parts[1], parts[2], int(parts[3]), int(parts[4]))


# ===========================================================================
# Step 1 — the card is presented to the RFID reader
# ===========================================================================

def read_card(bank, uid):
    """Ask the bank for the record, and decide whether to continue.

    Returns a Card if the session may proceed, otherwise None.
    """
    reply = bank.request(f"GET:{uid}")
    if reply is None:
        return None

    # The bank says it has never seen this card.
    if reply == "NONE":
        atm("Card not recognised by the bank.")
        screen("CARD NOT RECOGNISED", "Please take your card.")
        return None

    card = Card.parse(uid, reply)
    if card is None:
        atm(f"Unexpected reply from the bank: {reply}")
        screen("OUT OF SERVICE")
        return None

    # The bank reported the card as blocked. The ATM decides to refuse it.
    if card.locked:
        atm("Record says locked = 1. Refusing the card.")
        screen("CARD BLOCKED",
               "Please contact your branch.")
        return None

    atm(f"Card accepted: {card.name}, balance EGP {card.balance}.")
    return card


# ===========================================================================
# Step 2 — PIN entry (checked on the board, never sent to the bank)
# ===========================================================================

def check_pin(bank, card):
    """Ask for the PIN, up to MAX_PIN_ATTEMPTS times.

    Returns True if the customer got it right. If they run out of attempts the
    ATM locks the card itself and returns False.
    """
    for attempt in range(1, MAX_PIN_ATTEMPTS + 1):
        entered = ask(f"   Enter PIN ({attempt}/{MAX_PIN_ATTEMPTS}): ")
        if entered is None:
            return False

        # THE KEY LINE OF THE WHOLE PROJECT:
        # the comparison happens here, on the board. The typed PIN never
        # travels over the wire, and the bank is not asked to verify anything.
        if entered == card.pin:
            atm("PIN correct (compared on the board, nothing sent to the bank).")
            return True

        remaining = MAX_PIN_ATTEMPTS - attempt
        if remaining:
            atm(f"PIN incorrect. {remaining} attempt(s) left. Nothing sent.")
        else:
            atm(f"{MAX_PIN_ATTEMPTS} wrong attempts - the ATM decides to lock this card.")

    # Out of attempts: now, and only now, do we tell the bank.
    if bank.request(f"LOCK:{card.uid}") == "OK":
        screen("CARD BLOCKED",
               "Too many incorrect PIN entries.",
               "Please contact your branch.")
    else:
        screen("ERROR", "Please contact your branch.")
    return False


# ===========================================================================
# Step 3 — the menu
# ===========================================================================

def do_balance(card):
    """No request needed: the balance came back with the original GET."""
    atm("Answering from the record already in memory - no request sent.")
    screen(f"Account holder: {card.name}",
           f"Available balance: EGP {card.balance:,}")


def do_withdraw(bank, card):
    """Withdraw cash. Every check happens here before anything is sent."""
    raw = ask(f"   Amount to withdraw (multiples of {NOTE_SIZE}): ")
    if raw is None:
        return

    if not raw.isdigit() or int(raw) <= 0:
        atm("Not a valid amount. Nothing sent.")
        screen("INVALID AMOUNT")
        return

    amount = int(raw)

    # --- the three checks the STM32 must do, in order --------------------
    if amount % NOTE_SIZE != 0:
        atm(f"{amount} is not a multiple of {NOTE_SIZE}. Nothing sent.")
        screen(f"THIS MACHINE ONLY DISPENSES EGP {NOTE_SIZE} NOTES")
        return

    if amount > MAX_WITHDRAWAL:
        atm(f"{amount} is over the EGP {MAX_WITHDRAWAL} limit. Nothing sent.")
        screen(f"LIMIT IS EGP {MAX_WITHDRAWAL:,} PER TRANSACTION")
        return

    if amount > card.balance:
        atm(f"Insufficient funds: needs {amount}, has {card.balance}. Nothing sent.")
        screen("INSUFFICIENT FUNDS",
               f"Available: EGP {card.balance:,}")
        return

    # --- all checks passed: the ATM works out the new balance itself -----
    new_balance = card.balance - amount
    atm(f"Checks passed. New balance computed here: "
        f"{card.balance} - {amount} = {new_balance}")

    if bank.request(f"TXN:{card.uid}:WDR:{amount}:{new_balance}") != "OK":
        atm("The bank refused to record it - cancelling, no cash dispensed.")
        screen("TRANSACTION FAILED", "Please try again later.")
        return

    # Only update our copy once the bank confirmed it stored the new balance.
    card.balance = new_balance
    screen("PLEASE TAKE YOUR CASH",
           f"Dispensed: EGP {amount:,}",
           f"Remaining balance: EGP {card.balance:,}")


def do_deposit(bank, card):
    """Deposit cash. The machine counts the notes, so it sets the new total."""
    raw = ask(f"   Amount to deposit (multiples of {NOTE_SIZE}): ")
    if raw is None:
        return

    if not raw.isdigit() or int(raw) <= 0:
        atm("Not a valid amount. Nothing sent.")
        screen("INVALID AMOUNT")
        return

    amount = int(raw)
    if amount % NOTE_SIZE != 0:
        atm(f"{amount} is not a multiple of {NOTE_SIZE}. Nothing sent.")
        screen(f"THIS MACHINE ONLY ACCEPTS EGP {NOTE_SIZE} NOTES")
        return

    new_balance = card.balance + amount
    atm(f"Notes counted. New balance computed here: "
        f"{card.balance} + {amount} = {new_balance}")

    if bank.request(f"TXN:{card.uid}:DEP:{amount}:{new_balance}") != "OK":
        atm("The bank refused to record it - returning the notes.")
        screen("TRANSACTION FAILED", "Please take your notes back.")
        return

    card.balance = new_balance
    screen("DEPOSIT ACCEPTED",
           f"Credited: EGP {amount:,}",
           f"New balance: EGP {card.balance:,}")


def do_change_pin(bank, card):
    """Change the PIN. The ATM validates the format and the confirmation."""
    first = ask("   New 4-digit PIN: ")
    if first is None:
        return
    again = ask("   Re-enter the new PIN: ")
    if again is None:
        return

    if len(first) != 4 or not first.isdigit():
        atm("New PIN is not 4 digits. Nothing sent.")
        screen("PIN MUST BE 4 DIGITS")
        return

    if first != again:
        atm("The two entries did not match. Nothing sent.")
        screen("PINS DID NOT MATCH", "Please try again.")
        return

    if first == card.pin:
        atm("New PIN is the same as the old one. Nothing sent.")
        screen("PLEASE CHOOSE A DIFFERENT PIN")
        return

    if bank.request(f"PIN:{card.uid}:{first}") != "OK":
        screen("COULD NOT CHANGE PIN", "Please try again later.")
        return

    card.pin = first
    screen("PIN CHANGED SUCCESSFULLY",
           "Please remember your new PIN.")


MENU = """   +--------------------------------+
   |  1) Balance enquiry            |
   |  2) Withdraw cash              |
   |  3) Deposit cash               |
   |  4) Change PIN                 |
   |  5) Eject card                 |
   +--------------------------------+"""


def serve_customer(bank, card):
    """The menu loop, after a successful PIN entry."""
    screen(f"Welcome, {card.name}")

    while True:
        print(MENU)
        choice = ask("   Select 1-5: ")
        if choice is None or choice == "5":
            screen("PLEASE TAKE YOUR CARD", "Thank you for banking with us.")
            return

        if choice == "1":
            do_balance(card)
        elif choice == "2":
            do_withdraw(bank, card)
        elif choice == "3":
            do_deposit(bank, card)
        elif choice == "4":
            do_change_pin(bank, card)
        else:
            atm(f"'{choice}' is not on the menu.")


# ===========================================================================
# The idle loop — waiting for a card
# ===========================================================================

def run_atm(bank):
    print("=" * 64)
    print(" AAST BANK - ATM SIMULATOR")
    print(" Every decision below is made by the ATM. The bank only stores.")
    print("=" * 64)
    print(" Sample cards: A1B2C3D4 (Amro, PIN 1234)")
    print("               11223344 (Anas, PIN 4321)")
    print("               DEADBEEF (Guest, locked)")
    print("               FFFFFFFF (not in the bank)")
    print(" Type 'quit' at the card prompt to shut the machine down.\n")

    while True:
        screen("WELCOME TO AAST BANK", "Please insert your card.")

        uid = ask("   [Tap card on RFID reader - type a UID]: ")
        if uid is None or uid.lower() in ("quit", "exit"):
            print("\nATM shutting down.")
            return
        if not uid:
            continue

        uid = uid.upper()
        atm(f"RFID read UID {uid}. Asking the bank for the record...")

        card = read_card(bank, uid)
        if card is None:
            continue                     # bad card: straight back to idle

        if not check_pin(bank, card):
            continue                     # wrong PIN: back to idle

        serve_customer(bank, card)


def main():
    send_line, read_line, close, how = connect(sys.argv[1:])
    print(f"\nConnected to the bank via: {how}")
    try:
        run_atm(Bank(send_line, read_line))
    finally:
        close()
        print("Link closed.")


if __name__ == "__main__":
    main()
