"""
fake_stm32.py — the low-level protocol tool, and the shared connection layer.

TWO JOBS
--------
1. On its own, this is a debugging tool: you type ONE raw protocol line and it
   shows you the ONE line the bank sends back. Good for checking a single
   command or an error case.

2. It also holds the connection code that atm_gui.py and atm_sim.py both use,
   so the project has only one copy of it.

HOW THE PIECES CONNECT
----------------------
The BANK is the server and the ATMs are clients, exactly like the real world:
the bank sits there waiting, and cash machines connect to it.

    serial_listener.py --listen        <- the bank, waiting on port 5555
              ^
              |  protocol lines over localhost
              |
    atm_gui.py / atm_sim.py / fake_stm32.py    <- an ATM, connects in

So you always start the bank FIRST, then the ATM. If you start this before the
bank is ready it will keep retrying for a few seconds rather than give up.

With real hardware there is no socket at all — the STM32 is wired to a COM
port, and serial_listener.py reads that port instead.

USAGE
-----
    py fake_stm32.py                  connect to the bank on localhost:5555
    py fake_stm32.py --port COM5      talk over a real/virtual COM port instead

Commands to try:
    GET:A1B2C3D4                  -> REC:Amro:1234:2000:0
    GET:FFFFFFFF                  -> NONE
    TXN:A1B2C3D4:WDR:500:1500     -> OK
    PIN:A1B2C3D4:4321             -> OK
    LOCK:11223344                 -> OK
"""

import socket
import sys
import time

# Where the bank is listening. Must match serial_listener.py's LISTEN_PORT.
# We use 127.0.0.1 rather than "localhost" on purpose: on Windows "localhost"
# is tried as IPv6 first, which makes a failed connection take seconds instead
# of being refused instantly.
BANK_HOST = "127.0.0.1"
BANK_PORT = 5555

BAUD_RATE = 9600        # only used when talking to a real COM port

EXAMPLES = [
    "GET:A1B2C3D4",
    "GET:FFFFFFFF",
    "TXN:A1B2C3D4:WDR:500:1500",
    "TXN:A1B2C3D4:DEP:200:1700",
    "PIN:A1B2C3D4:4321",
    "LOCK:11223344",
]


class LinkBusy(Exception):
    """Raised when we cannot reach the bank. The message explains what to do."""


# ===========================================================================
# The connection layer.
#
# open_client_link() and open_serial_link() both return the same four things:
#
#   send_line(text) -> put one line on the wire
#   read_line()     -> wait for one line back (None if the link closed)
#   close()         -> hang up
#   description     -> a short string for the status bar
#
# Because they look identical from the outside, everything built on top works
# the same over localhost, over a virtual COM port, or over a real cable.
# ===========================================================================

def open_client_link(host=BANK_HOST, port=BANK_PORT, quiet=False,
                     attempts=6, delay=0.3):
    """Connect to the bank as a client, retrying briefly if it is still booting."""
    if not quiet:
        print(f"Connecting to the bank at {host}:{port} ...")

    sock = None
    for attempt in range(attempts):
        try:
            # A short timeout: a refused connection comes back instantly, so
            # this only caps how long we wait if something is really stuck.
            sock = socket.create_connection((host, port), timeout=0.5)
            break
        except OSError:
            time.sleep(delay)

    if sock is None:
        raise LinkBusy(
            f"Could not reach the bank at {host}:{port}.\n\n"
            f"Start the bank first, then this program:\n"
            f"  double-click 1_BANK.bat   (or run: py serial_listener.py --listen)"
        )

    # Generous timeout: the bank answers in microseconds, so if we ever wait
    # this long something is wrong and we want to notice rather than hang.
    sock.settimeout(10)
    buffer = b""

    def send_line(text):
        sock.sendall((text + "\n").encode("ascii"))

    def read_line():
        """Collect bytes until we have a full '\\n'-terminated line."""
        nonlocal buffer
        while b"\n" not in buffer:
            try:
                chunk = sock.recv(256)
            except OSError:
                return None                # timed out or the link broke
            if not chunk:
                return None                # the bank hung up
            buffer += chunk
        line, buffer = buffer.split(b"\n", 1)
        return line.decode("ascii", errors="replace").strip()

    def close():
        try:
            sock.close()
        except OSError:
            pass

    return send_line, read_line, close, f"bank at {host}:{port}"


def open_serial_link(port, quiet=False):
    """Open a real or virtual COM port (used when there IS hardware)."""
    import serial

    if not quiet:
        print(f"Opening {port} at {BAUD_RATE} baud (8N1)...")

    link = serial.serial_for_url(
        port,
        baudrate=BAUD_RATE,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=3,
    )

    def send_line(text):
        link.write((text + "\n").encode("ascii"))
        link.flush()

    def read_line():
        raw = link.readline()
        if not raw:
            return None                    # timed out
        return raw.decode("ascii", errors="replace").strip()

    def close():
        link.close()

    return send_line, read_line, close, port


def connect(args, quiet=False):
    """Pick the connection from the command line.

    --port COM5   -> a real or virtual serial port
    (nothing)     -> connect to the bank on localhost:5555
    """
    if "--port" in args:
        return open_serial_link(args[args.index("--port") + 1], quiet)
    return open_client_link(quiet=quiet)


# ===========================================================================
# The raw prompt loop (this file's own job)
# ===========================================================================

def print_banner(how):
    print("=" * 62)
    print(" FAKE STM32 - one raw protocol line at a time")
    print(f" Connected to: {how}")
    print("=" * 62)
    print(" Example requests:")
    for example in EXAMPLES:
        print(f"   {example}")
    print(" Type 'quit' to exit.\n")


def prompt_loop(send_line, read_line):
    while True:
        try:
            request = input("send> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nClosing.")
            return

        if request.lower() in ("quit", "exit"):
            print("Bye.")
            return
        if not request:
            continue

        send_line(request)
        print(f"  TX -> {request}")

        response = read_line()
        if response is None:
            print("  !! no response - the bank may have stopped.")
            return
        print(f"  RX <- {response}\n")


def main():
    try:
        send_line, read_line, close, how = connect(sys.argv[1:])
    except LinkBusy as err:
        print(f"\n{err}\n")
        return

    print_banner(how)
    try:
        prompt_loop(send_line, read_line)
    finally:
        close()
        print("Link closed.")


if __name__ == "__main__":
    main()
