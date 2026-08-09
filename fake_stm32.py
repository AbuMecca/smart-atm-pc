"""
fake_stm32.py — pretend to be the STM32 so you can test the whole protocol
                without any hardware.

It plays the role of the microcontroller: you type a request, it sends the
line, then it waits for the single response line the PC sends back.

Two ways to use it
------------------

1) SOCKET MODE (easiest — nothing to install, works out of the box)

   Terminal 1:  python fake_stm32.py
                -> it waits for the listener to connect

   Terminal 2:  python serial_listener.py --port socket://localhost:5555

   Then type commands in Terminal 1.

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
BAUD_RATE = 9600        # only used in virtual COM port mode

EXAMPLES = [
    "GET:A1B2C3D4",
    "GET:FFFFFFFF",
    "TXN:A1B2C3D4:WDR:500:1500",
    "TXN:A1B2C3D4:DEP:200:1700",
    "PIN:A1B2C3D4:4321",
    "LOCK:11223344",
]


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
    """Ask for a command, send it, print the one response line we get back.

    send_line(text) and read_line() are supplied by whichever mode we are in,
    so this loop does not care whether it is talking over TCP or a COM port.
    """
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


# ---------------------------------------------------------------------------
# Mode 1: TCP socket (no drivers needed)
# ---------------------------------------------------------------------------

def run_socket():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((SOCKET_HOST, SOCKET_PORT))
    server.listen(1)

    print(f"Waiting for serial_listener.py to connect on port {SOCKET_PORT}...")
    print("  In another terminal run:")
    print(f"  python serial_listener.py --port socket://{SOCKET_HOST}:{SOCKET_PORT}\n")

    conn, addr = server.accept()
    print_banner(f"socket {addr[0]}:{addr[1]}")

    buffer = b""

    def send_line(text):
        conn.sendall((text + "\n").encode("ascii"))

    def read_line():
        """Collect bytes until we have a full '\\n'-terminated line."""
        nonlocal buffer
        while b"\n" not in buffer:
            chunk = conn.recv(256)
            if not chunk:
                return None            # the other side hung up
            buffer += chunk
        line, buffer = buffer.split(b"\n", 1)
        return line.decode("ascii", errors="replace").strip()

    try:
        prompt_loop(send_line, read_line)
    finally:
        conn.close()
        server.close()


# ---------------------------------------------------------------------------
# Mode 2: real / virtual COM port
# ---------------------------------------------------------------------------

def run_serial(port):
    import serial

    print(f"Opening {port} at {BAUD_RATE} baud (8N1)...")
    link = serial.serial_for_url(
        port,
        baudrate=BAUD_RATE,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=3,
    )
    print_banner(port)

    def send_line(text):
        link.write((text + "\n").encode("ascii"))
        link.flush()

    def read_line():
        raw = link.readline()
        if not raw:
            return None                # timed out
        return raw.decode("ascii", errors="replace").strip()

    try:
        prompt_loop(send_line, read_line)
    finally:
        link.close()
        print(f"{port} closed.")


def main():
    args = sys.argv[1:]

    if "--port" in args:
        run_serial(args[args.index("--port") + 1])
    else:
        run_socket()


if __name__ == "__main__":
    main()
