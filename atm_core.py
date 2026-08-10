"""
atm_core.py — the rules of the ATM, with no screen and no wires.

This file answers one question: given what the bank told us and what the
customer typed, WHAT SHOULD THE ATM DO?

Nothing in here prints anything or touches the serial port. That is deliberate:

  * atm_sim.py  (text version) uses these rules
  * atm_gui.py  (window version) uses the same rules
  * the STM32 firmware must implement the same rules in C

Because all three share this one file, the text demo and the GUI demo can never
disagree with each other — and when you write the Blue Pill firmware, this is
the file to translate.

Every decision below is made HERE, on the ATM side. The PC is never asked
"is this PIN right?" or "can they afford this?". It is only ever told what to
store.
"""

# --- Bank policy. Change these and both the text and GUI ATMs follow. ------
MAX_PIN_ATTEMPTS = 3        # wrong PINs allowed before the card is locked
NOTE_SIZE = 50              # the cash tray only holds EGP 50 notes
MAX_WITHDRAWAL = 5000       # most that may be taken in one go


class Card:
    """What the bank knows about the card currently in the slot.

    The STM32 will keep this in a struct for the length of one session and
    update `balance` itself after each accepted transaction, so it only has to
    send one GET per customer.
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
        try:
            return Card(uid, parts[1], parts[2], int(parts[3]), int(parts[4]))
        except ValueError:
            return None                 # balance or locked was not a number


class Decision:
    """The answer to "what should the ATM do now?".

    approved  - True if the action may go ahead
    note      - the internal reason, shown as an "[ATM] ..." line in the demo
    screen    - the lines the customer should see
    request   - the protocol line to send, or None if nothing is sent
    amount    - how much money was involved (0 for non-money actions)
    balance   - the new balance to store locally once the bank replies OK
    """

    def __init__(self, approved, note, screen, request=None, amount=0, balance=None):
        self.approved = approved
        self.note = note
        self.screen = screen
        self.request = request
        self.amount = amount
        self.balance = balance


# ---------------------------------------------------------------------------
# Step 1 — a card was presented and the bank replied to our GET
# ---------------------------------------------------------------------------

def decide_card(uid, reply):
    """Work out whether this card may start a session.

    Returns (card, decision). `card` is None whenever the session must stop.
    """
    if reply is None:
        return None, Decision(False, "No answer from the bank.",
                              ["OUT OF SERVICE", "Please try again later."])

    if reply == "NONE":
        return None, Decision(False, "Card not recognised by the bank.",
                              ["CARD NOT RECOGNISED", "Please take your card."])

    card = Card.parse(uid, reply)
    if card is None:
        return None, Decision(False, f"Unexpected reply from the bank: {reply}",
                              ["OUT OF SERVICE"])

    if card.locked:
        return None, Decision(False, "Record says locked = 1. Refusing the card.",
                              ["CARD BLOCKED", "Please contact your branch."])

    return card, Decision(True,
                          f"Card accepted: {card.name}, balance EGP {card.balance}.",
                          [f"Welcome, {card.name}"])


# ---------------------------------------------------------------------------
# Step 2 — the PIN, compared on the board and never transmitted
# ---------------------------------------------------------------------------

def decide_pin(card, entered, attempt):
    """Check one PIN attempt. `attempt` counts from 1.

    This is the single most important function in the project. The comparison
    happens here; the typed PIN never goes near the serial port. The only time
    anything is sent is when the ATM itself decides to lock the card.
    """
    if entered == card.pin:
        return Decision(True,
                        "PIN correct (compared on the board, nothing sent).",
                        [])

    remaining = MAX_PIN_ATTEMPTS - attempt

    if remaining > 0:
        return Decision(False,
                        f"PIN incorrect. {remaining} attempt(s) left. Nothing sent.",
                        ["INCORRECT PIN",
                         f"{remaining} attempt(s) remaining."])

    # Out of attempts. Now — and only now — the ATM tells the bank.
    return Decision(False,
                    f"{MAX_PIN_ATTEMPTS} wrong attempts - the ATM locks this card.",
                    ["CARD BLOCKED",
                     "Too many incorrect PIN entries.",
                     "Please contact your branch."],
                    request=f"LOCK:{card.uid}")


# ---------------------------------------------------------------------------
# Step 3 — the money
# ---------------------------------------------------------------------------

def _parse_amount(raw):
    """Return a positive whole number, or None if the entry was nonsense."""
    raw = str(raw).strip()
    if not raw.isdigit():
        return None
    value = int(raw)
    return value if value > 0 else None


def decide_withdrawal(card, raw_amount):
    """Every check happens before a single byte is sent."""
    amount = _parse_amount(raw_amount)
    if amount is None:
        return Decision(False, "Not a valid amount. Nothing sent.",
                        ["INVALID AMOUNT"])

    if amount % NOTE_SIZE != 0:
        return Decision(False,
                        f"{amount} is not a multiple of {NOTE_SIZE}. Nothing sent.",
                        [f"THIS MACHINE ONLY DISPENSES",
                         f"EGP {NOTE_SIZE} NOTES"])

    if amount > MAX_WITHDRAWAL:
        return Decision(False,
                        f"{amount} is over the EGP {MAX_WITHDRAWAL} limit. Nothing sent.",
                        [f"LIMIT IS EGP {MAX_WITHDRAWAL:,}",
                         "PER TRANSACTION"])

    if amount > card.balance:
        return Decision(False,
                        f"Insufficient funds: needs {amount}, has {card.balance}. "
                        f"Nothing sent.",
                        ["INSUFFICIENT FUNDS",
                         f"Available: EGP {card.balance:,}"])

    # Approved. The ATM works out the new balance — the PC never calculates.
    new_balance = card.balance - amount
    return Decision(True,
                    f"Checks passed. New balance computed here: "
                    f"{card.balance} - {amount} = {new_balance}",
                    ["PLEASE TAKE YOUR CASH",
                     f"Dispensed: EGP {amount:,}",
                     f"Remaining balance: EGP {new_balance:,}"],
                    request=f"TXN:{card.uid}:WDR:{amount}:{new_balance}",
                    amount=amount,
                    balance=new_balance)


def decide_deposit(card, raw_amount):
    """The machine counts the notes, so it knows the new total."""
    amount = _parse_amount(raw_amount)
    if amount is None:
        return Decision(False, "Not a valid amount. Nothing sent.",
                        ["INVALID AMOUNT"])

    if amount % NOTE_SIZE != 0:
        return Decision(False,
                        f"{amount} is not a multiple of {NOTE_SIZE}. Nothing sent.",
                        [f"THIS MACHINE ONLY ACCEPTS",
                         f"EGP {NOTE_SIZE} NOTES"])

    new_balance = card.balance + amount
    return Decision(True,
                    f"Notes counted. New balance computed here: "
                    f"{card.balance} + {amount} = {new_balance}",
                    ["DEPOSIT ACCEPTED",
                     f"Credited: EGP {amount:,}",
                     f"New balance: EGP {new_balance:,}"],
                    request=f"TXN:{card.uid}:DEP:{amount}:{new_balance}",
                    amount=amount,
                    balance=new_balance)


def decide_pin_change(card, first, second):
    """Validate a new PIN locally before asking the bank to store it."""
    if len(first) != 4 or not first.isdigit():
        return Decision(False, "New PIN is not 4 digits. Nothing sent.",
                        ["PIN MUST BE 4 DIGITS"])

    if first != second:
        return Decision(False, "The two entries did not match. Nothing sent.",
                        ["PINS DID NOT MATCH", "Please try again."])

    if first == card.pin:
        return Decision(False, "New PIN is the same as the old one. Nothing sent.",
                        ["PLEASE CHOOSE A DIFFERENT PIN"])

    return Decision(True, "New PIN accepted locally. Asking the bank to store it.",
                    ["PIN CHANGED SUCCESSFULLY",
                     "Please remember your new PIN."],
                    request=f"PIN:{card.uid}:{first}")


def balance_screen(card):
    """A balance enquiry needs no request: the figure came with the GET."""
    return Decision(True,
                    "Answering from the record already in memory - no request sent.",
                    [f"Account holder: {card.name}",
                     f"Available balance: EGP {card.balance:,}"])
