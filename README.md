# Smart ATM — PC / Server Side

The PC side of a Smart ATM university project. This machine is the **bank
back-end**: it stores every account in a small SQLite database, answers the
ATM's requests over a serial (UART) port, and shows everything happening on a
bank-style web dashboard.

The ATM itself is an **STM32** microcontroller (keypad, LCD, RFID reader, servo).

> ### The one idea to explain first
> **The STM32 makes every decision.** It checks the PIN, it checks whether there
> is enough money, it counts the wrong attempts, and it works out the new
> balance. The PC has **no banking logic at all** — it only stores what it is
> told, answers lookups, and displays activity. This is deliberate. It is the
> first thing to point out when demonstrating the project.

---

## 0. QUICK START

**Double-click `DEMO.bat`.** That is the whole demo.

It starts the website and the STM32 serial listener, then opens the big ATM
screen in your browser. Press **F11** for full screen on the projector.

| Double-click | What it does |
|---|---|
| **`DEMO.bat`** | Starts everything and opens the ATM screen |
| **`ADMIN.bat`** | Cardholder admin menu (bank staff) |
| **`STOP.bat`** | Closes everything |

### The two screens

| Page | Who it is for | What it shows |
|---|---|---|
| **http://localhost:5000/atm** | the audience / customer | A live mirror of the STM32's screen. Big green ATM display. |
| **http://localhost:5000** | bank staff | All accounts, live transactions, ATM status |

Put `/atm` on the projector. Keep the dashboard on your laptop if you want to
show both.

### The ATM screen is a MIRROR, not a program

This is the most important thing to explain:

* The customer uses **the real card and the real keypad on the STM32**.
* The board decides everything and drives its own flow.
* As it goes, it shouts one-way `ST:` status messages down the serial cable.
* The web page just draws whichever screen was last reported.

The page has **no keypad that works** (the one drawn at the bottom is a
picture), no buttons, no inputs and no forms. **If the screen were switched
off entirely, the ATM would carry on working perfectly.**

---

## 1. Demoing without the STM32

You do not need the board to show the screen working.

`DEMO.bat` starts the listener in COM-port mode. If no board is connected it
prints that it could not open the port and drops into **manual mode**. Type
these into the **"AAST Bank - STM32 Link"** window and watch the big screen:

```
ST:IDLE
ST:PIN
ST:PINDOTS:1
ST:PINDOTS:4
ST:WRONGPIN:2
ST:WELCOME:Amro
ST:MENU:Amro
ST:BALANCE:2000
ST:DISPENSE:500
ST:THANKS
```

`ST:DISPENSE:500` is the good one for the audience: big amount plus banknotes
sliding out of the slot.

The same window still accepts the data requests (`GET:A1B2C3D4`,
`TXN:A1B2C3D4:WDR:500:1500`, ...) if you want to show the database changing.

---

## 2. The status messages (`ST:`)

These are **new, one-way, and never answered**. The board sends them purely so
the screen can follow along. They are separate from the four data commands,
which are unchanged.

| Message | Screen shows |
|---|---|
| `ST:IDLE` | "Please tap your card" (attract screen) |
| `ST:PIN` | "Enter your PIN" + empty dots |
| `ST:PINDOTS:<0-4>` | Fills that many dots (send one per key press) |
| `ST:WELCOME:<name>` | "Welcome &lt;name&gt;" |
| `ST:MENU:<name>` | The menu (1-4, and `*` to eject) |
| `ST:BALANCE:<n>` | "Your balance: EGP n" |
| `ST:DISPENSE:<n>` | "Dispensing EGP n" + cash animation |
| `ST:DEPOSIT:<n>` | "Deposit received: EGP n" |
| `ST:WRONGPIN:<k>` | "Wrong PIN - k tries left" (amber) |
| `ST:LOCKED` | "CARD LOCKED" (red) |
| `ST:PINCHANGED` | "PIN changed successfully" |
| `ST:THANKS` | "Thank you - please take your card" |

Rules for the firmware:

* **Never wait for a reply to an `ST:` message.** The PC sends nothing back.
* `ST:PIN` resets the dots to zero, so send it when PIN entry starts.
* Send `ST:PINDOTS:1`, `:2`, `:3`, `:4` as each digit is pressed.
* An unknown `ST:` message is logged and ignored; it will not crash anything.
* If the board sends no `ST:` messages at all, the screen still follows along
  roughly, because the listener also infers state from `GET`/`TXN`/`LOCK`.

### Result screens are held on purpose

The board announces something like `ST:DISPENSE:500` and then goes straight
back to `ST:MENU:Amro`. Without help the money screen would be wiped out
before anyone could read it — it was, and this is why it looked like the
dispense screen "did not work".

So the PC guarantees a minimum display time for the screens that announce a
**result**:

| Screen | Held for |
|---|---|
| `DISPENSE`, `DEPOSIT`, `LOCKED` | 3 seconds |
| `PINCHANGED`, `THANKS` | 2.5 seconds |

Everything else (`PIN`, `PINDOTS`, `MENU`, `BALANCE`, `WRONGPIN`) updates
instantly, so typing a PIN still feels immediate.

The board does not need to change or wait: it can send its next message
whenever it likes. The real state carries on updating underneath, and the
screen catches up the moment the hold expires. The hold lives in `app.py`
(`/api/atm_state`) and the durations are in `HOLD_SECONDS` at the top of
`serial_listener.py`.

After 60 seconds with nothing arriving, the screen returns to the attract
screen by itself.

---

## 3. Running it by hand (so you understand it)

```bash
cd C:\Users\amrho\Smart_ATM
```

Once only:

```bash
py -m pip install -r requirements.txt
```
```bash
py seed.py
```

Terminal 1 - the website:

```bash
py app.py
```

Terminal 2 - the link to the STM32:

```bash
py serial_listener.py
```

Then open **http://localhost:5000/atm** on the projector and
**http://localhost:5000** for the staff dashboard.

### The COM port

Set at the top of `serial_listener.py`, currently **COM5**:

```python
SERIAL_PORT = "COM5"
```

Check yours in **Device Manager -> Ports (COM & LPT)**. Or override it for one
run:

```bash
py serial_listener.py --port COM7
```

### Why `py` and not `python`?

On Windows, `python` often runs a **fake placeholder** that just prints:

```
Python was not found; run without arguments to install from the Microsoft Store
```

`py` is the official Windows Python Launcher and does not have this problem.
To fix `python` properly: **Settings -> Apps -> Advanced app settings -> App
execution aliases**, turn **off** `python.exe` and `python3.exe`, then open a
**new** terminal.

---

## 4. The web dashboard

Open **http://localhost:5000**. Everything refreshes every second.

### Live ATM Monitor (top panel)

A real-time mirror of what the STM32 is doing:

| Panel shows | Triggered by | Colour |
|---|---|---|
| `IDLE` — waiting for card | nothing for 60 seconds | grey |
| `CARD INSERTED` — awaiting PIN | a `GET` for a known, open card | blue |
| `UNKNOWN CARD` | a `GET` that returns `NONE` | amber |
| `CARD BLOCKED` | a `GET` for a card with `locked = 1` | red |
| `DISPENSING` | `TXN:...:WDR:...` | teal, flashing |
| `DEPOSIT` | `TXN:...:DEP:...` | green |
| `PIN CHANGED` | `PIN:...` | green |
| `CARD LOCKED` | `LOCK:...` | red, flashing |

**Important for your professor:** this panel is **display only**. It is worked
out from the messages the STM32 already sends — no new protocol was added, and
nothing here can control the ATM. If the monitor broke completely, the ATM
would carry on working exactly the same.

### Operations dashboard (below)

- Four summary figures: total accounts, total deposits held, locked cards,
  transactions logged.
- **Customer Accounts** — name, card UID, balance, Open/Locked.
- **Live Transactions** — newest first, with type, cardholder, amount, time.

### JSON API (what the page polls)

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/atm_state` | What the ATM is doing right now |
| `GET` | `/api/accounts` | All accounts |
| `GET` | `/api/transactions?limit=50` | Recent transactions |
| `POST` | `/api/accounts` | Add a cardholder (used by the web admin page) |
| `PUT` | `/api/accounts/<uid>` | Edit name / pin / balance / locked |
| `DELETE` | `/api/accounts/<uid>` | Delete a cardholder |

You can open any `GET` route straight in your browser to see the raw JSON —
a good way to show that the page holds no data of its own.

---

## 5. Managing cardholders — `admin_cli.py`

This is the **bank staff tool**, and the primary way to manage accounts:

```bash
py admin_cli.py
```

A numbered menu appears:

```
   1)  List all accounts
   2)  Add a new cardholder
   3)  Edit a balance
   4)  Lock / unlock a card
   5)  Delete a cardholder
   6)  Show recent transactions
   0)  Quit
```

It checks what you type (UID must be hex, name letters only, PIN exactly 4
digits) and asks again if it is wrong. Pressing **Enter** on its own cancels
whatever you were doing. Deleting asks for confirmation first.

It writes straight to `atm.db`, so a change is visible on the dashboard within
a second, and the STM32 sees it on that card's next `GET`.

> A web version also still exists at http://localhost:5000/admin if you prefer
> clicking, but the CLI is the primary interface.

---

## 6. The UART protocol

**Unchanged** from the original design.

* **9600 baud, 8 data bits, no parity, 1 stop bit (8N1)**
* Plain ASCII, fields separated by `:`, every line ends with `\n`
* The STM32 always asks first. The PC replies with **exactly one line** and
  never sends anything unprompted.

| Request from STM32 | Reply from PC | What the PC does |
|---|---|---|
| `GET:<uid>` | `REC:<name>:<pin>:<balance>:<locked>` or `NONE` | Look the card up |
| `TXN:<uid>:<type>:<amount>:<newbalance>` | `OK` or `ERR` | Store `<newbalance>`, log the event |
| `PIN:<uid>:<newpin>` | `OK` or `ERR` | Save the new PIN, log a `PIN` event |
| `LOCK:<uid>` | `OK` or `ERR` | Set `locked = 1`, log a `LOCK` event |

`<type>` is `WDR` (withdrawal) or `DEP` (deposit).

Rules worth remembering:

* **`NONE` is not `ERR`.** A `GET` for a card that does not exist returns
  `NONE`. `ERR` means the request was malformed or a write failed.
* On `TXN` the PC **does not recalculate anything**. The STM32 already worked
  out the new balance; the PC just writes that number down.
* A malformed line never crashes the listener — it is logged, answered with
  `ERR`, and the loop carries on.

### Setting the COM port

Open `serial_listener.py`. The constant is at the top, clearly marked:

```python
# ---------------------------------------------------------------------------
# CHANGE THIS to match your board.
#   Windows: "COM3", "COM4", ...        Linux/Mac: "/dev/ttyUSB0", ...
# ---------------------------------------------------------------------------
SERIAL_PORT = "COM3"
```

Or override it for one run without editing the file:

```bash
py serial_listener.py --port COM7
```

On Windows, check which port your board is on in **Device Manager → Ports
(COM & LPT)**.

### Worked example

```
STM32:  GET:A1B2C3D4
PC:     REC:Amro:1234:2000:0          (name, pin, balance, locked)

  ... the STM32 checks the PIN and the balance itself,
      then decides the new balance is 2000 - 500 = 1500 ...

STM32:  TXN:A1B2C3D4:WDR:500:1500
PC:     OK                            (balance is now 1500, event logged)
```

---

## 7. Looking at the database yourself — DB Browser for SQLite

The database is one ordinary file: **`atm.db`** in the project folder.

### Install

Download **DB Browser for SQLite** — free, from **https://sqlitebrowser.org**
(choose the standard Windows installer).

### Open the database

1. Open **DB Browser for SQLite**.
2. Click **Open Database** (top left).
3. Navigate to `C:\Users\amrho\Smart_ATM` and pick **`atm.db`**.
4. Click the **Browse Data** tab.
5. Use the **Table:** dropdown to switch between `accounts`, `transactions`
   and `atm_state`.

### Edit a row

1. In **Browse Data**, click the cell you want to change (for example Amro's
   `balance`).
2. Type the new value and press **Tab** or **Enter**.
3. Click **Write Changes** (Ctrl+S) in the toolbar. **Nothing is saved until
   you click Write Changes.**
4. The dashboard picks the change up within a second.

### Can I have it open while the app is running?

**Yes, for reading.** The database uses **WAL mode** (write-ahead logging),
switched on in `database.py`:

```python
cur.execute("PRAGMA journal_mode = WAL")
```

In SQLite's default mode a program that is writing blocks everyone else from
reading, and DB Browser shows "database is locked". WAL lets readers and one
writer work at the same time, so you can watch the tables live while the ATM
is running.

Two practical notes:

* Every function in `database.py` **opens a connection, does its work, and
  closes it again**. The app never sits holding the file open, which is the
  other half of why DB Browser can get in.
* If you want to **write** from DB Browser while the app is running, click
  **Write Changes** promptly — holding an unsaved edit keeps a transaction
  open. If you ever do see "database is locked", just close the two app
  windows, make your edit, and start again.
* WAL creates two extra files next to the database, `atm.db-wal` and
  `atm.db-shm`. That is normal. Do not delete them while the app is running.

### Starting over

Close the app, delete `atm.db` (and the `-wal`/`-shm` files if present), then:

```bash
py seed.py
```

---

## 8. The retired software ATM

Earlier versions had `atm_gui.py` / `atm_sim.py`: a self-contained software
ATM with a working on-screen keypad, which connected to the listener over a
socket on port 5555.

**That is retired.** The real STM32 is now the only ATM, and the PC screen is
just a mirror of it. The files are still in the folder so you can see how it
worked, but nothing launches them and the demo does not use them.

If you ever want to run the old software ATM again:

```bash
py serial_listener.py --listen
```
```bash
py atm_gui.py
```

That still works, but do not use it for the demo — the mirror screen at
`/atm` is what the brief asks for.

### Checking the data commands by hand

`fake_stm32.py` sends one raw protocol line and shows the reply. Manual mode
in the listener (`py serial_listener.py --manual`) does the same thing without
needing a second program, and is usually easier.

---

## 9. Database schema

SQLite, one file: `atm.db`.

**`accounts`**

| Column | Type | Meaning |
|---|---|---|
| `uid` | TEXT, primary key | RFID card UID as hex text, e.g. `A1B2C3D4` |
| `name` | TEXT | Cardholder name, letters only |
| `pin` | TEXT | 4 digits — kept as **text** so `"0000"` does not become `0` |
| `balance` | INTEGER | Whole EGP, no decimals |
| `locked` | INTEGER | `0` = open, `1` = locked |

**`transactions`**

| Column | Type | Meaning |
|---|---|---|
| `id` | INTEGER, autoincrement | Row number |
| `uid` | TEXT | Which card |
| `type` | TEXT | `WDR`, `DEP`, `PIN` or `LOCK` |
| `amount` | INTEGER | `0` for the non-money events |
| `timestamp` | TEXT | ISO datetime string |

**`atm_state`** — a single row (`id` is always 1) holding what the ATM is doing
right now, so the dashboard can draw the live monitor. Written by the serial
listener, read by the website. It is a mirror, not a control.

Sample accounts created by `seed.py`:

| UID | Name | PIN | Balance | Status |
|---|---|---|---|---|
| `A1B2C3D4` | Amro | 1234 | 2000 | Open |
| `11223344` | Anas | 4321 | 500 | Open |
| `DEADBEEF` | Guest | 0000 | 100 | Locked |

---

## 10. Troubleshooting

**`Python was not found; run without arguments to install from the Microsoft
Store`** — use `py` instead of `python`, or turn off the aliases as described
in §3. Remember to open a **new** terminal afterwards.

**`Could not open COM3`** — the port name is wrong or something else is using
it. Check **Device Manager → Ports (COM & LPT)**, and close any Arduino Serial
Monitor or PuTTY window holding the port. The listener falls back to manual
mode so you can keep working.

**Dashboard shows no data** — run `py seed.py`; `atm.db` may not exist yet.

**Dashboard is not updating** — look at the Serial Listener window. If it
prints `TX -> ERR`, the request format is wrong. If it prints nothing at all,
nothing is arriving on the port.

**`ModuleNotFoundError: No module named 'flask'`** — run
`py -m pip install -r requirements.txt`.

**Port 5000 already in use** — an old copy is still running. Run
`STOP.bat`, or change the last line of `app.py` to `port=5001`.

**The ATM screen shows NO LINK** — the website stopped. Check the
"AAST Bank - Website" window, or run `DEMO.bat` again.

**DB Browser says "database is locked"** — close the two app windows, make
your edit, click Write Changes, then start the app again. See §7.

---

## 11. What each file does

| File | What it does |
|---|---|
| `app.py` | The Flask website: the `/atm` mirror screen, the staff dashboard, and the JSON APIs they poll. |
| `serial_listener.py` | The UART loop. The 4 data commands **and** the new one-way `ST:` status messages. **COM port constant at the top.** |
| `database.py` | Every SQLite query. Also turns on WAL mode (see §7). |
| `admin_cli.py` | The bank staff admin menu. |
| `seed.py` | Creates `atm.db` with the 3 sample cardholders. |
| `show_db.py` | Prints the raw database in the terminal, no web server needed. |
| `templates/atm_screen.html` | **The big ATM mirror screen.** Display only. |
| `templates/dashboard.html` | The staff operations dashboard. |
| `templates/admin.html` | Optional web admin page (the CLI is the primary one). |
| `static/atm.css` | The green-screen ATM look. |
| `static/style.css` | The navy/blue bank theme for the dashboard. |
| `DEMO.bat` / `ADMIN.bat` / `STOP.bat` | The launchers. |
| `atm.db` | The database file (created by `seed.py`). |
| `atm_gui.py`, `atm_sim.py`, `atm_core.py`, `fake_stm32.py` | The **retired** software ATM (see §8). Kept for reference; not used by the demo. |

### Where the "no banking logic on the PC" rule lives

* `serial_listener.py` stores the balance the STM32 sends. It never adds or
  subtracts anything.
* There is no PIN check anywhere on the PC. The board compares the PIN itself
  and only tells us the outcome (`ST:WRONGPIN:2`, or a `LOCK:` command).
* `templates/atm_screen.html` has no buttons, inputs or forms at all — you can
  verify that by searching the file.
