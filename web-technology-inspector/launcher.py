
"""Cross-platform Streamlit launcher with port retry."""

import os
import socket
import subprocess
import sys
import time

START_PORT = 8501
END_PORT = 8599
HOST = "127.0.0.1"


def is_port_available(port):
    """Check whether a TCP port can be bound locally."""
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    ) as sock:
        try:
            sock.bind((HOST, port))
            return True
        except OSError:
            return False


def start_streamlit(port):
    """Start Streamlit and return its process."""
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "app.py",
        "--server.address",
        HOST,
        "--server.port",
        str(port),
        "--server.headless",
        "true",
    ]

    return subprocess.Popen(
        command,
        cwd=os.path.dirname(
            os.path.abspath(__file__)
        ),
    )


def main():
    print("=" * 48)
    print("Web Technology Inspector")
    print("=" * 48)

    for port in range(
        START_PORT,
        END_PORT + 1
    ):
        if not is_port_available(port):
            print(
                f"Port {port} is occupied. "
                "Trying next port..."
            )
            continue

        print(
            f"Starting application at "
            f"http://{HOST}:{port}"
        )

        process = start_streamlit(port)

        # Give Streamlit time to start.
        time.sleep(3)

        code = process.poll()

        if code is not None:
            print(
                f"Streamlit exited with code {code}."
            )

            # Retry only when port became occupied.
            if not is_port_available(port):
                print(
                    "Port conflict detected. Retrying..."
                )
                continue

            print(
                "Startup failed for a reason "
                "other than a port conflict."
            )
            return code or 1

        try:
            return process.wait()

        except KeyboardInterrupt:
            print("\nStopping application...")

            process.terminate()

            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

            return 0

    print(
        f"No available port between "
        f"{START_PORT} and {END_PORT}."
    )

    return 1


if __name__ == "__main__":
    sys.exit(main())
