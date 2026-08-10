"""
fake_stm32.py — pretend to be the STM32 so you can test the protocol
                without any hardware.

This is the LOW-LEVEL tool: you type one raw request line, it sends it, and it
prints the one response line the PC sends back. Use it to check individual
commands and error cases.

For the full cash-machine experience (scan card -> PIN -> menu -> withdraw),
run `python atm_sim.py` instead. It uses the same connection code from this
file, but adds the decision-making the real STM32 will do.

Two ways to connect
-------------------

1) SOCKET MODE (easiest — nothing to install, works out of the box)

   Terminal 1:  python fake_stm32.py
                -> it waits for the listener to connect

   Terminal 2:  python serial_listener.py --port socket://localhost:5555

   Here fake_stm32.py is a tiny TCP server and serial_listener.py connects to
   it as a pyserial "socket://" port. The bytes travel over localhost instead
   of a wire, but serial_listener.py runs its real serial code either way.

2) VIRTUAL COM PORT MODE (closest to the real thing)

   Install a virtual null-modem driver that gives you a linked pair of ports
   (com0com on Windows -> e.g. COM4 <-> COM5, or `socat` on Linux).

   Terminal 1:  python fake_stm32.py --port COM5
   Terminal 2:  python serial_listener.py --port COM4

Commands to try
---------------
   GET:A1B2C3D4                  -> REC:Amro:1234:2000:0
   GET:FFFFFFFF                  -> NONE
   TXN:A1B2C3D4:WDR:500:1500     -> OK
   TXN:A1B2C3D4:DEP:200:1700     -> OK
   PIN:A1B2C3D4:4321             -> OK
   LOCK:11223344                 -> OK
"""

import socket
import sys

SOCKET_HOST = "localhost"
SOCKET_PORT = 5555      # only used in socket mode
BAUD_RATE = 9600        # only used in COM port mode

EXAMPLES = [
    "GET:A1B2C3D4",
    "GET:FFFFFFFF",
    "TXN:A1B2C3D4:WDR:500:1500",
    "TXN:A1B2C3D4:DEP:200:1700",
    "PIN:A1B2C3D4:4321",
    "LOCK:11223344",
]


# ===========================================================================
# The connection layer.
#
# Both open_socket_link() and open_serial_link() return the same three things:
#
#   send_line(text) -> put one line on the wire
#   read_line()     -> wait for one line back (None if the link closed)
#   close()         -> hang up
#
# Because they look identical from the outside, everything above this layer
# (this file's prompt loop, and the whole of atm_sim.py) works the same way
# over a socket, a virtual COM port, or a real cable to the STM32.
# ===========================================================================

class LinkBusy(Exception):
    """Raised when the socket port is already taken by another simulator."""


def open_socket_link(quiet=False):
    """Act as a tiny TCP server and wait for serial_listener.py to connect."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        # Windows only. Without this, a SECOND copy of this program is allowed
        # to bind the same port and will silently steal the listener's
        # connection from the first copy - which looks like the ATM simply
        # hanging. This makes the second copy fail immediately instead.
        server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        # Linux/Mac: lets the port be reused straight after a restart.
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind((SOCKET_HOST, SOCKET_PORT))
    except OSError as err:
        server.close()
        raise LinkBusy(
            f"Port {SOCKET_PORT} is already in use ({err}).\n"
            f"Another atm_gui.py, atm_sim.py or fake_stm32.py is probably still\n"
            f"running. Close it and try again."
        ) from None

    server.listen(1)

    if not quiet:
        print(f"Waiting for serial_listener.py to connect on port {SOCKET_PORT}...")
        print("  In another terminal run:")
        print(f"  python serial_listener.py --port socket://{SOCKET_HOST}:{SOCKET_PORT}\n")

    conn, addr = server.accept()
    buffer = b""

    def send_line(text):
        conn.sendall((text + "\n").encode("ascii"))

    def read_line():
        """Collect bytes until we have a full '\\n'-terminated line."""
        nonlocal buffer
        while b"\n" not in buffer:
            try:
                chunk = conn.recv(256)
            except OSError:
                return None                # the link broke
            if not chunk:
                return None                # the other side hung up
            buffer += chunk
        line, buffer = buffer.split(b"\n", 1)
        return line.decode("ascii", errors="replace").strip()

    def close():
        conn.close()
        server.close()

    return send_line, read_line, close, f"socket {addr[0]}:{addr[1]}"


def open_serial_link(port, quiet=False):
    """Open a real or virtual COM port."""
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
    """Pick the connection type from the command line: --port COMx, or socket."""
    if "--port" in args:
        return open_serial_link(args[args.index("--port") + 1], quiet)
    return open_socket_link(quiet)


# ===========================================================================
# The raw prompt loop
# ===========================================================================

def print_banner(how):
    print("=" * 62)
    print(" FAKE STM32 - pretending to be the ATM front panel")
    print(f" Connected via: {how}")
    print("=" * 62)
    print(" Example requests:")
    for example in EXAMPLES:
        print(f"   {example}")
    print(" Type 'quit' to exit.\n")


def prompt_loop(send_line, read_line):
    """Ask for a raw command, send it, print the single response line."""
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
            print("  !! no response (is serial_listener.py running?)")
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
