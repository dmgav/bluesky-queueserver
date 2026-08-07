import os
import time as ttime

import pytest

from bluesky_queueserver.manager.profile_ops import clear_registered_items


@pytest.fixture(scope="session", autouse=True)
def print_open_file_descriptors():
    yield
    ttime.sleep(1)
    pid = os.getpid()
    fd_dir = f"/proc/{pid}/fd"
    fd_entries = sorted(os.listdir(fd_dir), key=int)
    msg = f"\n+++ PID={pid} OPEN FILE DESCRIPTORS = {len(fd_entries)}\n"
    # /dev/tty bypasses all pytest capture layers
    try:
        with open("/dev/tty", "w") as tty:
            tty.write(msg)
    except OSError:
        import sys

        sys.stderr.write(msg)
        sys.stderr.flush()


@pytest.fixture(autouse=True)
def setup_and_teardown_for_every_test():
    print("Clearing registered items ...")
    clear_registered_items()
    yield
    print("Clearing registered items ...")
    clear_registered_items()
