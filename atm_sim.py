"""
atm_sim.py — a full ATM session in the terminal, with no hardware.

    Scan card -> enter PIN -> menu -> withdraw / deposit / change PIN -> eject

This is the text version. `atm_gui.py` is the same machine with a window,
a keypad and an LCD. Both get their rules from atm_core.py, so they always
behave identically.

WHY THIS FILE MATTERS
---------------------
Every decision is made HERE, on the ATM side — never on the PC:

  * Is this card known / blocked?  -> read from the GET reply
  * Is the PIN correct?            -> compared locally, never transmitted
  * Three wrong tries?             -> this side decides to send LOCK
  * Enough money to withdraw?      -> checked before anything is sent
  * What is the new balance?       -> calculated here, then sent in TXN

The PC only stores what it is told. Read atm_core.py alongside this file:
that is the part which becomes the STM32 firmware.

HOW TO RUN
----------
  Terminal 1:  python atm_sim.py
  Terminal 2:  python serial_listener.py --port socket://localhost:5555

  Or against a virtual COM pair (com0com / socat):
  Terminal 1:  python atm_sim.py --port COM5
  Terminal 2:  python serial_listener.py --port COM4

Keep http://localhost:5000 open — the portal updates live.
"""

import sys

import atm_core
from atm_core import (MAX_PIN_ATTEMPTS, balance_screen, decide_card,
                      decide_deposit, decide_pin, decide_pin_change,
                      decide_withdrawal)
# Reuse the connection layer so there is only one copy of the socket/COM code.
from fake_stm32 import LinkBusy, connect


# ===========================================================================
# Screen helpers
# ===========================================================================

def screen(lines):
    """Print what the cardholder would see on the ATM display."""
    print()
    for line in lines:
        print(f"   | {line}")
    print()


def atm(message):
    """Print a decision the ATM made internally — no traffic to the bank."""
    if message:
        print(f"  [ATM] {message}")


def ask(prompt):
    """Read one line. Returns None if the user wants out."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None


class Bank:
    """One request, one response — with the traffic printed for the demo."""

    def __init__(self, send_line, read_line):
        self._send = send_line
        self._read = read_line

    def request(self, message):
        print(f"  TX -> {message}")
        self._send(message)
        reply = self._read()
        if reply is None:
            print("  !! the bank did not answer (is serial_listener.py running?)")
            return None
        print(f"  RX <- {reply}")
        return reply


# ===========================================================================
# Step 1 — the card is presented to the RFID reader
# ===========================================================================

def read_card(bank, uid):
    """Ask the bank for the record and decide whether to continue."""
    reply = bank.request(f"GET:{uid}")
    card, decision = decide_card(uid, reply)
    atm(decision.note)
    if card is None:
        screen(decision.screen)
    return card


# ===========================================================================
# Step 2 — PIN entry, checked on the board and never transmitted
# ===========================================================================

def check_pin(bank, card):
    """Up to MAX_PIN_ATTEMPTS tries. Locks the card if they all fail."""
    for attempt in range(1, MAX_PIN_ATTEMPTS + 1):
        entered = ask(f"   Enter PIN ({attempt}/{MAX_PIN_ATTEMPTS}): ")
        if entered is None:
            return False

        decision = decide_pin(card, entered, attempt)
        atm(decision.note)

        if decision.approved:
            return True

        # Only the final failure carries a request (LOCK).
        if decision.request:
            if bank.request(decision.request) == "OK":
                screen(decision.screen)
            else:
                screen(["ERROR", "Please contact your branch."])
            return False

        screen(decision.screen)

    return False


# ===========================================================================
# Step 3 — the menu
# ===========================================================================

def do_money(bank, card, kind):
    """Withdraw or deposit. `kind` is "WDR" or "DEP"."""
    word = "withdraw" if kind == "WDR" else "deposit"
    raw = ask(f"   Amount to {word} (multiples of {atm_core.NOTE_SIZE}): ")
    if raw is None:
        return

    decide = decide_withdrawal if kind == "WDR" else decide_deposit
    decision = decide(card, raw)
    atm(decision.note)

    if not decision.approved:
        screen(decision.screen)      # refused here; nothing was sent
        return

    if bank.request(decision.request) != "OK":
        atm("The bank did not confirm - cancelling.")
        screen(["TRANSACTION FAILED", "Please try again later."])
        return

    # Only update our copy once the bank confirmed the write.
    card.balance = decision.balance
    screen(decision.screen)


def do_change_pin(bank, card):
    first = ask("   New 4-digit PIN: ")
    if first is None:
        return
    again = ask("   Re-enter the new PIN: ")
    if again is None:
        return

    decision = decide_pin_change(card, first, again)
    atm(decision.note)

    if not decision.approved:
        screen(decision.screen)
        return

    if bank.request(decision.request) != "OK":
        screen(["COULD NOT CHANGE PIN", "Please try again later."])
        return

    card.pin = first
    screen(decision.screen)


MENU = """   +--------------------------------+
   |  1) Balance enquiry            |
   |  2) Withdraw cash              |
   |  3) Deposit cash               |
   |  4) Change PIN                 |
   |  5) Eject card                 |
   +--------------------------------+"""


def serve_customer(bank, card):
    """The menu loop, after a successful PIN entry."""
    screen([f"Welcome, {card.name}"])

    while True:
        print(MENU)
        choice = ask("   Select 1-5: ")
        if choice is None or choice == "5":
            screen(["PLEASE TAKE YOUR CARD", "Thank you for banking with us."])
            return

        if choice == "1":
            decision = balance_screen(card)
            atm(decision.note)
            screen(decision.screen)
        elif choice == "2":
            do_money(bank, card, "WDR")
        elif choice == "3":
            do_money(bank, card, "DEP")
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
        screen(["WELCOME TO AAST BANK", "Please insert your card."])

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
            continue                     # bad card: back to idle

        if not check_pin(bank, card):
            continue                     # wrong PIN: back to idle

        serve_customer(bank, card)


def main():
    try:
        send_line, read_line, close, how = connect(sys.argv[1:])
    except LinkBusy as err:
        print(f"\n{err}\n")
        return
    print(f"\nConnected to the bank via: {how}")
    try:
        run_atm(Bank(send_line, read_line))
    finally:
        close()
        print("Link closed.")


if __name__ == "__main__":
    main()
