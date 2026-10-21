"""Find an available local TCP port."""

import socket
import sys


def find_port(start=8501, end=8599):
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue

    raise RuntimeError(
        f"No available port between {start} and {end}"
    )


if __name__ == "__main__":
    try:
        print(find_port())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
