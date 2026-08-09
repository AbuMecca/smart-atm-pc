# Smart ATM — PC / Server Side

The PC side of a Smart ATM university project. This machine acts as the **bank
back-end**: it stores every account in a small SQLite database and serves a
bank-style web portal. An **STM32** microcontroller (the ATM front panel) talks
to it over a serial (UART) COM port.

> **The most important idea in this project:** the STM32 makes all the
> decisions. It checks the PIN, it checks whether there is enough money, and it
> works out the new balance. The PC has **no banking logic at all** — it only
> stores what it is told, answers lookups, and displays activity. This is
> deliberate, and it is the first thing to explain when demonstrating the
> project.

---

## 1. Files

| File | What it does |
|---|---|
| `database.py` | Every SQLite query lives here (create tables, read/update accounts, log transactions). |
| `seed.py` | Creates `atm.db` and inserts the 3 sample cardholders. |
| `app.py` | The Flask web server: two pages plus a small JSON API. |
| `serial_listener.py` | The UART loop. Implements the 4 protocol commands. |
| `fake_stm32.py` | Pretends to be the STM32 so the protocol can be tested with no hardware. |
| `show_db.py` | Prints the raw database (schema + both tables) with no web server involved. |
| `templates/portal.html` | Main dashboard — accounts + live transaction feed. |
| `templates/admin.html` | Bank staff screen — add / edit / lock / delete cardholders. |
| `static/style.css` | The navy/blue bank theme. |
| `atm.db` | The database file itself (created by `seed.py`). |

---

## 2. How to run it

```bash
pip install -r requirements.txt
```

```bash
python seed.py
```
Creates `atm.db` and inserts the sample accounts. It prints the table
afterwards so you can see it worked. Running it twice is safe — existing
accounts are left alone.

```bash
python app.py
```
Starts the web portal at **http://localhost:5000**. Leave this terminal open.

```bash
python serial_listener.py
```
Starts the COM-port listener **in a second terminal**. Leave this open too.

Both programs share the same `atm.db` file. That is how activity from the ATM
shows up on the web portal a moment later.

### Setting the COM port

Open `serial_listener.py` and change the constant near the top:

```python
SERIAL_PORT = "COM3"        # Windows
# SERIAL_PORT = "/dev/ttyUSB0"   # Linux / Mac
```

Or override it for one run without editing the file:

```bash
python serial_listener.py --port COM7
```

Every line sent and received is printed to the console (`RX <-` and `TX ->`),
which makes the demo easy to follow and easy to debug.

---

## 3. The UART protocol

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
  `NONE`. `ERR` means the request itself was bad or a write failed.
* On `TXN` the PC **does not recalculate anything**. The STM32 already worked
  out the new balance; the PC just writes that number down.
* A malformed line never crashes the listener. It is logged and answered with
  `ERR`, and the loop carries on.

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

## 4. Testing the protocol with **no STM32 hardware**

There are three ways, easiest first.

### Option A — manual mode (nothing to install)

```bash
python serial_listener.py --manual
```

You get an `STM32>` prompt. Type request lines yourself and see the exact reply
the real board would get:

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
be opened, it drops into this mode automatically.

You can also pipe a whole script of test commands in at once:

```bash
python serial_listener.py --manual < my_test_commands.txt
```

### Option B — `fake_stm32.py` over a socket (tests the *real* serial loop)

Manual mode skips the actual serial reading code. This option exercises it,
still with nothing to install.

Terminal 1:
```bash
python fake_stm32.py
```

Terminal 2:
```bash
python serial_listener.py --port socket://localhost:5555
```

Now type commands at the `send>` prompt in Terminal 1. `fake_stm32.py` acts as
a tiny TCP server, and `serial_listener.py` connects to it using pyserial's
`socket://` port type. The bytes travel over localhost instead of a wire, but
`serial_listener.py` is running its genuine serial code — same `readline()`,
same `write()`, same everything.

### Option C — a virtual COM port pair (closest to real hardware)

Install a virtual null-modem driver that gives you two linked ports:

* **Windows:** [com0com](https://sourceforge.net/projects/com0com/) — creates
  e.g. `COM4` linked to `COM5`.
* **Linux:** `socat -d -d pty,raw,echo=0 pty,raw,echo=0`

Terminal 1:
```bash
python fake_stm32.py --port COM5
```

Terminal 2:
```bash
python serial_listener.py --port COM4
```

Anything typed into `fake_stm32.py` now travels through a real (virtual) serial
driver. When the actual STM32 arrives, nothing changes except the port name.

### Full test script

Paste these into whichever mode you chose to exercise every command and every
error path:

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

Keep http://localhost:5000 open on screen while you do this — the balances and
the transaction feed update within 2 seconds of each command.

---

## 5. The web portal

### `/` — Dashboard
* Four summary cards: total accounts, total deposits held, locked cards,
  transactions logged.
* **Customer Accounts** table: name, card UID, balance, Open/Locked status.
* **Live Transactions** feed: newest first, with type, cardholder, amount and
  time.
* Both refresh every 2 seconds, so ATM activity appears live during the demo.

### `/admin` — Cardholder Admin
* Issue a new card (UID, name, PIN, opening balance), with validation:
  UID must be 4–16 hex characters, name letters only, PIN exactly 4 digits.
* Per cardholder: **Edit Balance**, **Lock / Unlock**, **Delete**.
* These write straight to `atm.db`. This is the bank staff path and is entirely
  separate from the ATM's serial path — but both share the one database, so a
  change made here is visible to the STM32 on its next `GET`.

### JSON API

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/accounts` | All accounts |
| `POST` | `/api/accounts` | Add a cardholder |
| `PUT` | `/api/accounts/<uid>` | Edit name / pin / balance / locked |
| `DELETE` | `/api/accounts/<uid>` | Delete a cardholder |
| `GET` | `/api/transactions?limit=50` | Recent transactions, newest first |

---

## 6. Database

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
| `amount` | INTEGER | `0` for the non-money events (`PIN`, `LOCK`) |
| `timestamp` | TEXT | ISO datetime string |

Sample accounts created by `seed.py`:

| UID | Name | PIN | Balance | Status |
|---|---|---|---|---|
| `A1B2C3D4` | Amro | 1234 | 2000 | Open |
| `11223344` | Anas | 4321 | 500 | Open |
| `DEADBEEF` | Guest | 0000 | 100 | Locked |

### Starting over

Delete `atm.db` and run `python seed.py` again to get back to a clean demo
state.

---

## 7. Troubleshooting

**`Could not open COM3`** — the port name is wrong or something else is using
it. On Windows check Device Manager → Ports (COM & LPT). Close any Arduino
Serial Monitor or PuTTY window holding the port. The listener falls back to
manual mode so you can keep working.

**Portal shows no data** — run `python seed.py` first; `atm.db` may not exist.

**Portal is not updating** — check the `serial_listener.py` terminal. If it is
printing `TX -> ERR`, the request format is wrong. If it prints nothing at all,
nothing is arriving on the port.

**`ModuleNotFoundError: No module named 'flask'`** — run
`pip install -r requirements.txt`.

**`Python was not found; run without arguments to install from the Microsoft
Store`** — Windows is finding its placeholder `python.exe` in
`%LOCALAPPDATA%\Microsoft\WindowsApps` instead of the real one. Fix the order
of your user PATH so the real Python comes first:

```powershell
$real = "$env:LOCALAPPDATA\Python\bin"
$user = [Environment]::GetEnvironmentVariable("Path","User")
[Environment]::SetEnvironmentVariable("Path", "$real;" + ($user -replace [regex]::Escape("$real;"), ""), "User")
```

Then **open a new terminal** — PATH changes only apply to newly started
terminals. (Alternatively: Settings → Apps → Advanced app settings → App
execution aliases → turn off the `python.exe` and `python3.exe` aliases.)

**Port 5000 already in use** — change the last line of `app.py` to a different
port, e.g. `port=5001`.
