from multiprocessing import Process
import json
from pathlib import Path
import socket
import time

from flask import Flask, request
from appdirs import user_data_dir

from src.pytest_fly.__version__ import application_name, author

current_test = 0  # assume test 0 starts unconditionally

current_test_key = "current_test"
completed_key = "completed"


def _get_http_port_file_path() -> Path:
    http_port_file_path = Path(user_data_dir(application_name, author), f"{application_name}_http_port.txt")
    return http_port_file_path


def _find_open_port(start_port: int = 8000, end_port: int = 9000) -> int:
    """
    Finds an open local HTTP port in the specified range.

    Args:
        start_port (int): Starting port number for the search.
        end_port (int): Ending port number for the search.

    Returns:
        int: An open port number.
    """
    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("localhost", port))  # Using localhost instead of 127.0.0.1
                return port  # Port is available
            except OSError:
                continue  # Try the next port

    raise RuntimeError(f"No open ports available in range {start_port}-{end_port}")


def init_port():
    """
    Initializes the port for the local HTTP server.
    """

    http_port_file_path = _get_http_port_file_path()
    http_port_file_path.parent.mkdir(parents=True, exist_ok=True)
    open_port = _find_open_port()
    http_port_file_path.open("w").write(f"{open_port}")


def remove_port():
    """
    Removes the port file.
    """

    http_port_file_path = _get_http_port_file_path()
    http_port_file_path.unlink(missing_ok=True)


def _get_port() -> int:
    """
    Returns the URL for the local HTTP server.

    Returns:
        str: The URL for the local HTTP server.
    """
    http_port_file_path = _get_http_port_file_path()
    if not http_port_file_path.exists():
        time.sleep(1)  # wait for the file to be created
    file_contents = http_port_file_path.open().read()
    port = int(file_contents)
    return port


def get_http_url() -> str:
    """
    Returns the URL for the local HTTP server.

    Returns:
        str: The URL for the local HTTP server.
    """
    port = _get_port()
    url = f"http://localhost:{port}/"
    return url


class Orchestrator(Process):

    def run(self):

        app = Flask(__name__)

        @app.route("/", methods=["GET", "POST"])
        def home():
            global current_test

            if request.method == "POST":
                post_request = request.get_json()
                print(f"{post_request=}")

                completed = post_request.get(completed_key)
                if completed is None:
                    raise ValueError(f'"{completed_key}" key not found in post request')
                elif completed == current_test:
                    # test is done, go to the next one
                    current_test += 1
                elif completed < current_test:
                    raise ValueError(f"completed test {completed} is less than current test {current_test}")

            response = json.dumps({current_test_key: current_test})
            return response

        print("Starting orchestrator")
        app.run(port=_get_port())
        print("Orchestrator done")
