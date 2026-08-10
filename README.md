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

## 1. What each file does

| File | What it does |
|---|---|
| `app.py` | The Flask web server: the dashboard page plus the JSON APIs it polls. |
| `database.py` | Every SQLite query lives here. Also turns on WAL mode (see §7). |
| `serial_listener.py` | The UART loop. Implements the 4 protocol commands. **COM port constant is at the top.** |
| `admin_cli.py` | **The bank staff admin tool** — a menu in the terminal. |
| `seed.py` | Creates `atm.db` and inserts the 3 sample cardholders. |
| `start_atm.bat` | One-click launcher: starts everything and opens the browser. |
| `stop_atm.bat` | Closes the two windows the launcher opened. |
| `templates/dashboard.html` | The operations dashboard + live ATM monitor. |
| `templates/admin.html` | Optional web admin page (the CLI is the primary one now). |
| `static/style.css` | The navy/blue bank theme. |
| `atm.db` | The database file itself (created by `seed.py`). |
| `show_db.py` | Prints the raw database in the terminal, no web server needed. |
| `atm_sim.py` | A full ATM session simulated in the terminal (no hardware). |
| `atm_gui.py` | The same ATM simulation as a window with a keypad (no hardware). |
| `atm_core.py` | The ATM's decision rules, shared by both simulators. |
| `fake_stm32.py` | Low-level tool: send one raw protocol line, see the reply. |

---

## 2. Running it — Method A: one click (easiest)

**Double-click `start_atm.bat`.**

That is the whole thing. It will:

1. Move into the project folder, wherever you have put it.
2. Use a `.venv` virtual environment if one exists, otherwise the `py` launcher.
3. Install Flask and pyserial the first time, if they are missing.
4. Create `atm.db` with the sample accounts if it does not exist yet.
5. Open **two black windows** — the Web Portal and the Serial Listener.
6. Open your browser at **http://localhost:5000**.

**To stop everything:** close those two windows, or double-click `stop_atm.bat`.

Leave both windows open during your demo. The Serial Listener window is worth
showing to your professor — every line the STM32 sends and every line the PC
replies with is printed there as it happens.

---

## 3. Running it — Method B: by hand (so you understand it)

Open a terminal (press `Win`, type `powershell`, press Enter), then:

```bash
cd C:\Users\amrho\Smart_ATM
```

**Step 1 — install the two libraries (once only):**

```bash
py -m pip install -r requirements.txt
```

**Step 2 — create the database (once only):**

```bash
py seed.py
```

It prints the accounts table afterwards so you can see it worked. Running it
again is safe — existing accounts are left alone.

**Step 3 — start the web portal.** Leave this terminal open:

```bash
py app.py
```

Then open **http://localhost:5000** in your browser.

**Step 4 — start the serial listener in a SECOND terminal.** Leave it open too:

```bash
py serial_listener.py
```

Both programs share the same `atm.db` file. That is how activity from the ATM
appears on the dashboard a moment later — they never talk to each other
directly.

### Why `py` and not `python`?

On Windows, `python` often runs a **fake placeholder** that Microsoft installs,
which just prints:

```
Python was not found; run without arguments to install from the Microsoft Store
```

`py` is the official Windows Python Launcher and does not have this problem, so
every example above uses it.

**To fix `python` properly** (optional):

> **Settings → Apps → Advanced app settings → App execution aliases**
> → turn **off** `python.exe` and `python3.exe`.

After that, close and reopen your terminal. Note that PATH and alias changes
only affect **newly opened** terminals — an already-open window keeps the old
settings, which is the usual reason a fix "doesn't work".

---

## 4. The web dashboard

Open **http://localhost:5000**. Everything refreshes every second.

### Live ATM Monitor (top panel)

A real-time mirror of what the STM32 is doing:

| Panel shows | Triggered by | Colour |
|---|---|---|
| `IDLE` — waiting for card | nothing for 25 seconds | grey |
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

## 8. Testing the whole thing with **no STM32**

Four ways, easiest first. All of them make the dashboard and the live monitor
react exactly as the real board would.

### Option A — manual mode (nothing to install)

```bash
py serial_listener.py --manual
```

You get an `STM32>` prompt. Type request lines yourself:

```
STM32> GET:A1B2C3D4
  RX <- GET:A1B2C3D4
  TX -> REC:Amro:1234:2000:0
STM32> TXN:A1B2C3D4:WDR:500:1500
  TX -> OK
STM32> GET:FFFFFFFF
  TX -> NONE
```

Type `quit` to exit. If you start the listener normally and the COM port cannot
be opened, it drops into this mode automatically — which is exactly what
happens when you run `start_atm.bat` with no board plugged in.

### Option B — the ATM simulator with a window

The full cash-machine experience: an LCD, a keypad, and a card reader.

Terminal 1:
```bash
py atm_gui.py
```

Terminal 2:
```bash
py serial_listener.py --port socket://localhost:5555
```

Click a sample card to "tap" it, type the PIN on the keypad, use the menu.
`atm_sim.py` is the same thing as a text menu if you prefer the terminal.

Every decision is made inside the simulator, never on the PC:

| Decision | Made by | Sent to the bank? |
|---|---|---|
| Is the card known / blocked? | read from the `GET` reply | — |
| Is the PIN correct? | compared on the board | **No.** The typed PIN never leaves the ATM |
| 3 wrong PINs → lock the card | the ATM decides | then `LOCK:<uid>` |
| Enough money to withdraw? | checked before sending | nothing sent if it fails |
| What is the new balance? | calculated on the board | sent inside `TXN` |

Watch the `[ATM]` lines: those are the board thinking, with no traffic to the
bank at all. `atm_core.py` holds these rules and is effectively the
**specification for the STM32 firmware**.

### Option C — one raw line at a time

```bash
py fake_stm32.py
```
```bash
py serial_listener.py --port socket://localhost:5555
```

Sends exactly what you type and shows exactly what comes back. Best for
checking a single command or an error case.

### Option D — a virtual COM port pair (closest to real hardware)

Install a virtual null-modem driver that gives you two linked ports —
[com0com](https://sourceforge.net/projects/com0com/) on Windows (e.g. `COM4`
linked to `COM5`), or `socat` on Linux.

```bash
py atm_gui.py --port COM5
```
```bash
py serial_listener.py --port COM4
```

Now the bytes travel through a real serial driver. When the STM32 arrives,
nothing changes except the port name.

### Full test script

Paste these to exercise every command and every error path:

```
GET:A1B2C3D4                  -> REC:Amro:1234:2000:0
GET:FFFFFFFF                  -> NONE          (unknown card)
TXN:A1B2C3D4:WDR:500:1500     -> OK
TXN:A1B2C3D4:DEP:200:1700     -> OK
GET:A1B2C3D4                  -> REC:Amro:1234:1700:0
PIN:A1B2C3D4:4321             -> OK
LOCK:11223344                 -> OK
GET:11223344                  -> REC:Anas:4321:500:1   (locked = 1)
TXN:FFFFFFFF:WDR:100:0        -> ERR           (no such card)
TXN:A1B2C3D4:XYZ:100:1600     -> ERR           (bad type)
TXN:A1B2C3D4:WDR:abc:1600     -> ERR           (bad number)
PIN:A1B2C3D4:12               -> ERR           (PIN must be 4 digits)
HELLO                         -> ERR           (unknown command)
GET:A1B2C3D4:extra            -> ERR           (wrong field count)
```

Keep http://localhost:5000 on screen while you do this.

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
`stop_atm.bat`, or change the last line of `app.py` to `port=5001`.

**`Port 5555 is already in use`** from a simulator — another `atm_gui.py`,
`atm_sim.py` or `fake_stm32.py` is still open. Close it and try again.

**DB Browser says "database is locked"** — close the two app windows, make
your edit, click Write Changes, then start the app again. See §7.
