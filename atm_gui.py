"""
atm_gui.py — the ATM as a window: LCD screen, keypad, card reader.

Same machine as atm_sim.py, same rules from atm_core.py, but with a front panel
you can click instead of a text prompt. Good for the demo, and it looks like
the real thing you are building: a small screen, a numeric keypad, and an RFID
reader.

HOW TO RUN
----------
  Terminal 1:  python atm_gui.py
  Terminal 2:  python serial_listener.py --port socket://localhost:5555

  Or against a virtual COM pair (com0com / socat):
  Terminal 1:  python atm_gui.py --port COM5
  Terminal 2:  python serial_listener.py --port COM4

Keep http://localhost:5000 open next to it — the portal updates live.

A NOTE ON THREADS
-----------------
Reading from the serial port BLOCKS: the program stops and waits for bytes to
arrive. In a console program that is fine. In a window it is not — the whole
window would freeze and stop redrawing.

So all the link work happens on a second thread (`LinkWorker`). That thread
never touches a widget — tkinter may only be driven from the thread that made
the window. Instead the worker drops each result into a `queue.Queue`, and the
window checks that queue every 40 ms and does the drawing itself. The window
therefore stays responsive even while waiting for the bank.
"""

import queue
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont

import atm_core
from atm_core import (MAX_PIN_ATTEMPTS, Card, balance_screen, decide_card,
                      decide_deposit, decide_pin, decide_pin_change,
                      decide_withdrawal)
from fake_stm32 import connect

# --- Colours: a dark ATM shell with a green LCD ---------------------------
SHELL = "#12233d"        # the machine's body
PANEL = "#0a1f44"        # darker recesses
LCD_BG = "#0b2016"       # screen background
LCD_FG = "#7CFFA0"       # screen text
LCD_DIM = "#3f7f57"      # faded screen text
KEY_BG = "#e8edf5"       # keypad buttons
KEY_FG = "#12233d"
ENTER_BG = "#2e9e5b"
CANCEL_BG = "#c0392b"
CLEAR_BG = "#b7791f"
LOG_BG = "#08111f"

# The cards lying next to the machine, for tapping on the reader.
SAMPLE_CARDS = [
    ("Amro",         "A1B2C3D4"),
    ("Anas",         "11223344"),
    ("Guest",        "DEADBEEF"),
    ("Unknown card", "FFFFFFFF"),
]


# ===========================================================================
# The background thread that owns the serial link
# ===========================================================================

class LinkWorker:
    """Owns the connection and does every send/receive off the UI thread.

    Usage:  worker.send("GET:A1B2C3D4", my_callback)
    `my_callback(reply)` is then called back ON the UI thread.
    """

    POLL_MS = 40        # how often the UI thread checks for finished work

    def __init__(self, root, args, on_status):
        self._root = root
        self._args = args
        self._on_status = on_status          # called with a status string
        self._jobs = queue.Queue()           # UI thread -> worker thread
        self._results = queue.Queue()        # worker thread -> UI thread
        self._send_line = None
        self._read_line = None
        self._close = None
        self._stopped = False

        threading.Thread(target=self._run, daemon=True).start()
        self._poll()                         # starts on the UI thread

    # -- runs on the worker thread ----------------------------------------
    def _run(self):
        try:
            self._send_line, self._read_line, self._close, how = \
                connect(self._args, quiet=True)
        except Exception as err:
            self._post(self._on_status, f"Link failed: {err}")
            return

        self._post(self._on_status, f"Connected via {how}")

        while True:
            request, callback = self._jobs.get()
            if request is None:              # shutdown signal
                break
            try:
                self._send_line(request)
                reply = self._read_line()
            except Exception as err:
                self._post(self._on_status, f"Link error: {err}")
                reply = None
            self._post(callback, reply)

    def _post(self, function, argument):
        """Called on the WORKER thread: park the result for the UI thread.

        We deliberately do NOT touch any widget here, and do not call
        root.after() either — tkinter is only safe to drive from the thread
        that created the window. Dropping the result in a queue is the safe
        handover; _poll() below picks it up on the UI thread.
        """
        self._results.put((function, argument))

    # -- runs on the UI thread --------------------------------------------
    def _poll(self):
        """Every POLL_MS, deliver whatever the worker has finished."""
        while True:
            try:
                function, argument = self._results.get_nowait()
            except queue.Empty:
                break
            function(argument)

        if not self._stopped:
            self._root.after(self.POLL_MS, self._poll)

    # -- called from the UI thread ----------------------------------------
    def send(self, request, callback):
        self._jobs.put((request, callback))

    def shutdown(self):
        self._stopped = True
        self._jobs.put((None, None))
        if self._close:
            try:
                self._close()
            except Exception:
                pass


# ===========================================================================
# The window
# ===========================================================================

class ATMApp:
    """The ATM front panel.

    `link` is anything with .send(request, callback). The real one is a
    LinkWorker; the tests pass a stub so the rules can be exercised without a
    serial port.
    """

    def __init__(self, root, link=None, args=None):
        self.root = root
        root.title("AAST Bank — ATM")
        root.configure(bg=SHELL)
        root.geometry("980x660")
        root.minsize(880, 600)

        # --- session state ------------------------------------------------
        self.card = None            # the Card currently in the slot
        self.state = "IDLE"
        self.entry = ""             # what the customer has typed so far
        self.pin_attempt = 0
        self.new_pin = ""           # first entry while changing a PIN
        self.busy = False           # True while we are waiting for the bank

        self._build_ui()

        self.link = link or LinkWorker(root, args or [], self._set_status)
        self.go_idle()

    # ------------------------------------------------------------------
    # Building the panel
    # ------------------------------------------------------------------

    def _build_ui(self):
        mono = tkfont.Font(family="Consolas", size=11)
        self.lcd_font = tkfont.Font(family="Consolas", size=15, weight="bold")

        # --- header -------------------------------------------------------
        header = tk.Frame(self.root, bg=PANEL, height=58)
        header.pack(fill="x")
        tk.Label(header, text="  AAST BANK", bg=PANEL, fg="white",
                 font=("Segoe UI", 17, "bold")).pack(side="left", pady=12)
        self.status = tk.Label(header, text="starting...", bg=PANEL, fg="#8fa8cc",
                               font=("Segoe UI", 10))
        self.status.pack(side="right", padx=16)

        body = tk.Frame(self.root, bg=SHELL)
        body.pack(fill="both", expand=True, padx=16, pady=14)

        # --- left: the LCD screen ----------------------------------------
        left = tk.Frame(body, bg=SHELL)
        left.pack(side="left", fill="both", expand=True)

        screen_shell = tk.Frame(left, bg="#061a10", bd=4, relief="sunken")
        screen_shell.pack(fill="both", expand=True)

        self.lcd = tk.Label(screen_shell, bg=LCD_BG, fg=LCD_FG, font=self.lcd_font,
                            justify="center", anchor="center", text="",
                            wraplength=460, padx=18, pady=18)
        self.lcd.pack(fill="both", expand=True)

        # The line that shows what is being typed (PIN dots or an amount).
        self.entry_label = tk.Label(screen_shell, bg=LCD_BG, fg="white",
                                    font=("Consolas", 26, "bold"), text="",
                                    pady=10)
        self.entry_label.pack(fill="x")

        # --- card reader ---------------------------------------------------
        reader = tk.LabelFrame(left, text=" RFID CARD READER — tap a card ",
                               bg=SHELL, fg="#8fa8cc", font=("Segoe UI", 9, "bold"),
                               bd=1, labelanchor="nw")
        reader.pack(fill="x", pady=(12, 0))

        self.card_buttons = []
        row = tk.Frame(reader, bg=SHELL)
        row.pack(fill="x", padx=8, pady=8)
        for label, uid in SAMPLE_CARDS:
            button = tk.Button(row, text=f"{label}\n{uid}", font=("Consolas", 9),
                               bg="#dbe5f5", fg=KEY_FG, relief="raised", bd=2,
                               width=13, height=2, cursor="hand2",
                               command=lambda u=uid: self.tap_card(u))
            button.pack(side="left", padx=4)
            self.card_buttons.append(button)

        # --- right: keypad --------------------------------------------------
        right = tk.Frame(body, bg=SHELL)
        right.pack(side="right", fill="y", padx=(16, 0))

        pad = tk.Frame(right, bg=PANEL, padx=10, pady=10)
        pad.pack()

        self.keys = []
        layout = [("1", "2", "3"), ("4", "5", "6"), ("7", "8", "9")]
        for r, keys in enumerate(layout):
            for c, key in enumerate(keys):
                self._key(pad, key, r, c, KEY_BG, lambda k=key: self.press_digit(k))

        self._key(pad, "CLEAR", 3, 0, CLEAR_BG, self.press_clear, fg="white", small=True)
        self._key(pad, "0", 3, 1, KEY_BG, lambda: self.press_digit("0"))
        self._key(pad, "ENTER", 3, 2, ENTER_BG, self.press_enter, fg="white", small=True)
        self._key(pad, "CANCEL", 4, 0, CANCEL_BG, self.press_cancel,
                  fg="white", small=True, span=3)

        # Let the physical keyboard drive it too — much faster to demo.
        self.root.bind("<Key>", self._on_keyboard)

        # --- bottom: serial monitor ----------------------------------------
        monitor = tk.LabelFrame(self.root, text=" SERIAL MONITOR — what crosses the wire ",
                                bg=SHELL, fg="#8fa8cc",
                                font=("Segoe UI", 9, "bold"), bd=1)
        monitor.pack(fill="both", padx=16, pady=(0, 14))

        self.log = tk.Text(monitor, height=9, bg=LOG_BG, fg="#c9d6e8", font=mono,
                           bd=0, padx=10, pady=8, state="disabled", wrap="none")
        self.log.pack(fill="both", expand=True)
        self.log.tag_config("tx", foreground="#6fb1ff")
        self.log.tag_config("rx", foreground="#7CFFA0")
        self.log.tag_config("atm", foreground="#f0c05a")
        self.log.tag_config("dim", foreground="#66788f")

    def _key(self, parent, text, row, col, bg, command, fg=KEY_FG,
             small=False, span=1):
        button = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                           font=("Consolas", 10 if small else 15, "bold"),
                           width=8 if small else 5, height=2, bd=2,
                           relief="raised", cursor="hand2",
                           activebackground=bg)
        button.grid(row=row, column=col, columnspan=span, padx=4, pady=4,
                    sticky="nsew")
        self.keys.append(button)
        return button

    # ------------------------------------------------------------------
    # Screen and log helpers
    # ------------------------------------------------------------------

    def show(self, *lines):
        """Put text on the LCD."""
        self.lcd.config(text="\n\n".join(lines))

    def _set_status(self, text):
        self.status.config(text=text)
        self.write_log(text, "dim")

    def write_log(self, text, tag="dim"):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.config(state="disabled")

    def log_decision(self, decision):
        """Show the ATM's internal reasoning — the point of the whole demo."""
        if decision.note:
            self.write_log(f"  [ATM] {decision.note}", "atm")

    def _refresh_entry(self):
        """Show the typed digits: dots for a PIN, plain numbers for an amount."""
        if self.state in ("PIN", "NEWPIN1", "NEWPIN2"):
            self.entry_label.config(text="●" * len(self.entry))
        elif self.state in ("WITHDRAW", "DEPOSIT"):
            self.entry_label.config(text=f"EGP {self.entry}" if self.entry else "")
        else:
            self.entry_label.config(text="")

    def set_state(self, state):
        self.state = state
        self._refresh_entry()
        # The card reader only works when no session is running.
        for button in self.card_buttons:
            button.config(state="normal" if state == "IDLE" else "disabled")

    # ------------------------------------------------------------------
    # Talking to the bank
    # ------------------------------------------------------------------

    def ask_bank(self, request, callback):
        """Send one line and hand the reply to `callback` when it arrives."""
        self.busy = True
        self.write_log(f"  TX -> {request}", "tx")
        self.link.send(request, lambda reply: self._reply(reply, callback))

    def _reply(self, reply, callback):
        self.busy = False
        if reply is None:
            self.write_log("  !! no answer from the bank", "atm")
        else:
            self.write_log(f"  RX <- {reply}", "rx")
        callback(reply)

    # ------------------------------------------------------------------
    # The states
    # ------------------------------------------------------------------

    def go_idle(self):
        self.card = None
        self.entry = ""
        self.pin_attempt = 0
        self.new_pin = ""
        self.set_state("IDLE")
        self.show("WELCOME TO AAST BANK", "Please present your card")

    def tap_card(self, uid):
        """An RFID card was held against the reader."""
        if self.state != "IDLE" or self.busy:
            return
        self.write_log("")
        self.write_log(f"  [ATM] RFID read UID {uid}. Asking the bank...", "atm")
        self.show("READING CARD...")
        self.ask_bank(f"GET:{uid}", lambda reply: self._card_reply(uid, reply))

    def _card_reply(self, uid, reply):
        card, decision = decide_card(uid, reply)
        self.log_decision(decision)

        if card is None:
            self.show(*decision.screen)
            self.root.after(2600, self.go_idle)
            return

        self.card = card
        self.pin_attempt = 0
        self.entry = ""
        self.set_state("PIN")
        self.show(f"Welcome, {card.name}", "Please enter your PIN")

    # --- PIN ----------------------------------------------------------

    def _submit_pin(self):
        if len(self.entry) != 4:
            self.show("PIN MUST BE 4 DIGITS", "Please try again")
            self.entry = ""
            self._refresh_entry()
            return

        self.pin_attempt += 1
        decision = decide_pin(self.card, self.entry, self.pin_attempt)
        self.entry = ""
        self._refresh_entry()
        self.log_decision(decision)

        if decision.approved:
            self.go_menu()
            return

        # Wrong PIN. If the ATM decided to lock the card, tell the bank now.
        if decision.request:
            self.set_state("BUSY")
            self.show(*decision.screen)
            self.ask_bank(decision.request,
                          lambda reply: self.root.after(2600, self.go_idle))
        else:
            self.show(*decision.screen)

    # --- menu ---------------------------------------------------------

    MENU_TEXT = ("1  Balance enquiry\n"
                 "2  Withdraw cash\n"
                 "3  Deposit cash\n"
                 "4  Change PIN\n"
                 "5  Eject card")

    def go_menu(self):
        self.entry = ""
        self.set_state("MENU")
        self.show(f"{self.card.name} — please choose", self.MENU_TEXT)

    def _menu_choice(self, key):
        if key == "1":
            decision = balance_screen(self.card)
            self.log_decision(decision)
            self.show(*decision.screen)
            self.root.after(3000, self.go_menu)
            self.set_state("BUSY")
        elif key == "2":
            self.entry = ""
            self.set_state("WITHDRAW")
            self.show("WITHDRAW",
                      f"Enter amount in multiples of {atm_core.NOTE_SIZE}",
                      "then press ENTER")
        elif key == "3":
            self.entry = ""
            self.set_state("DEPOSIT")
            self.show("DEPOSIT",
                      f"Insert notes and enter the total",
                      "then press ENTER")
        elif key == "4":
            self.entry = ""
            self.set_state("NEWPIN1")
            self.show("CHANGE PIN", "Enter a new 4-digit PIN")
        elif key == "5":
            self.eject()

    # --- money ----------------------------------------------------------

    def _submit_amount(self, kind):
        decide = decide_withdrawal if kind == "WDR" else decide_deposit
        decision = decide(self.card, self.entry)
        self.entry = ""
        self.log_decision(decision)

        if not decision.approved:
            # Refused by the ATM itself — nothing was sent to the bank.
            self.set_state("BUSY")
            self.show(*decision.screen)
            self.root.after(3000, self.go_menu)
            return

        self.set_state("BUSY")
        self.show("PLEASE WAIT...")
        self.ask_bank(decision.request,
                      lambda reply: self._money_reply(reply, decision))

    def _money_reply(self, reply, decision):
        if reply != "OK":
            self.write_log("  [ATM] Bank did not confirm - cancelling.", "atm")
            self.show("TRANSACTION FAILED", "Please try again later")
            self.root.after(3000, self.go_menu)
            return

        # Only now update our local copy of the balance.
        self.card.balance = decision.balance
        self.show(*decision.screen)
        self.root.after(3600, self.go_menu)

    # --- PIN change -------------------------------------------------------

    def _submit_new_pin(self):
        if self.state == "NEWPIN1":
            self.new_pin = self.entry
            self.entry = ""
            self.set_state("NEWPIN2")
            self.show("CHANGE PIN", "Re-enter the new PIN")
            return

        decision = decide_pin_change(self.card, self.new_pin, self.entry)
        self.entry = ""
        self.new_pin = ""
        self.log_decision(decision)

        if not decision.approved:
            self.set_state("BUSY")
            self.show(*decision.screen)
            self.root.after(3000, self.go_menu)
            return

        self.set_state("BUSY")
        self.ask_bank(decision.request,
                      lambda reply: self._pin_change_reply(reply, decision))

    def _pin_change_reply(self, reply, decision):
        if reply != "OK":
            self.show("COULD NOT CHANGE PIN", "Please try again later")
        else:
            self.card.pin = decision.request.split(":")[2]
            self.show(*decision.screen)
        self.root.after(3000, self.go_menu)

    def eject(self):
        self.set_state("BUSY")
        self.show("PLEASE TAKE YOUR CARD", "Thank you for banking with us")
        self.root.after(2600, self.go_idle)

    # ------------------------------------------------------------------
    # Keypad
    # ------------------------------------------------------------------

    def press_digit(self, key):
        if self.busy:
            return

        if self.state == "MENU":
            self._menu_choice(key)
            return

        if self.state in ("PIN", "NEWPIN1", "NEWPIN2"):
            if len(self.entry) < 4:
                self.entry += key
        elif self.state in ("WITHDRAW", "DEPOSIT"):
            if len(self.entry) < 7:
                self.entry += key
        else:
            return

        self._refresh_entry()

    def press_clear(self):
        if self.busy:
            return
        self.entry = ""
        self._refresh_entry()

    def press_enter(self):
        if self.busy:
            return
        if self.state == "PIN":
            self._submit_pin()
        elif self.state in ("NEWPIN1", "NEWPIN2"):
            if len(self.entry) == 4:
                self._submit_new_pin()
        elif self.state == "WITHDRAW":
            self._submit_amount("WDR")
        elif self.state == "DEPOSIT":
            self._submit_amount("DEP")

    def press_cancel(self):
        if self.busy:
            return
        if self.state == "IDLE":
            return
        if self.state == "MENU" or self.card is None:
            self.eject()
        else:
            # Back out of whatever the customer was typing.
            self.entry = ""
            self.new_pin = ""
            self.go_menu()

    def _on_keyboard(self, event):
        """Let the real keyboard work: digits, Enter, Backspace, Escape."""
        if event.char.isdigit():
            self.press_digit(event.char)
        elif event.keysym in ("Return", "KP_Enter"):
            self.press_enter()
        elif event.keysym in ("BackSpace", "Delete"):
            self.press_clear()
        elif event.keysym == "Escape":
            self.press_cancel()


def main():
    root = tk.Tk()
    app = ATMApp(root, args=sys.argv[1:])

    def on_close():
        if isinstance(app.link, LinkWorker):
            app.link.shutdown()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
