import pytest
from xprocess import ProcessStarter

# import socket

import time as ttime

import bluesky_queueserver.server.server as bqss
from bluesky_queueserver.manager.comms import zmq_single_request

SERVER_ADDRESS = "localhost"
SERVER_PORT = "60610"


@pytest.fixture
def fastapi_server(xprocess):
    class Starter(ProcessStarter):
        pattern = "Connected to ZeroMQ server"
        args = f"uvicorn --host={SERVER_ADDRESS} --port {SERVER_PORT} {bqss.__name__}:app".split()

    xprocess.ensure("fastapi_server", Starter)

    yield

    xprocess.getinfo("fastapi_server").terminate()


@pytest.fixture
def fastapi_server_modified(xprocess):
    def _request_to_json(request_type, path, **kwargs):
        import requests

        resp = getattr(requests, request_type)(f"http://{SERVER_ADDRESS}:{SERVER_PORT}{path}", **kwargs).json()
        return resp

    def start():
        nonlocal xprocess

        class Starter(ProcessStarter):
            # pattern = "Connected to ZeroMQ server"
            pattern = "Uvicorn running on"
            args = f"uvicorn --host={SERVER_ADDRESS} --port {SERVER_PORT} {bqss.__name__}:app".split()

        print("Pausing before starting the server ...")
        # ttime.sleep(1)
        print("Starting the server ...")
        server_started = False
        for _ in range(30):
            try:
                xprocess.ensure("fastapi_server", Starter)
                resp1 = _request_to_json("get", "/")
                assert resp1["msg"] == "RE Manager"
                server_started = True
                break
            except Exception as ex:
                print("Error occurred while starting the server", ex)
                xprocess.getinfo("fastapi_server").terminate()
            ttime.sleep(1)
        if not server_started:
            raise Exception("Failed to start the web server")

        print("Pausing ...")
        # ttime.sleep(1)
        print("Process started")

    yield start

    print("Stopping the server ...")
    xprocess.getinfo("fastapi_server").terminate()
    print("Server is stopped")

    # t = ttime.time() + 30  # set timeout
    # while True:
    #     if ttime.time() > t:
    #         raise Exception("uivcorn failed to release the socket - next test would fail")
    #     try:
    #         socket.create_connection(("localhost", 60610), 10)
    #     except ConnectionRefusedError:
    #         break
    #     ttime.sleep(1)
    # print("Checked that the socket was released")


def add_plans_to_queue():
    """
    Clear the queue and add 3 fixed plans to the queue.
    Raises an exception if clearing the queue or adding plans fails.
    """
    resp1, _ = zmq_single_request("queue_clear")
    assert resp1["success"] is True, str(resp1)

    user_group = "admin"
    user = "HTTP unit test setup"
    plan1 = {"name": "count", "args": [["det1", "det2"]], "kwargs": {"num": 10, "delay": 1}}
    plan2 = {"name": "count", "args": [["det1", "det2"]]}
    for plan in (plan1, plan2, plan2):
        resp2, _ = zmq_single_request("queue_item_add", {"plan": plan, "user": user, "user_group": user_group})
        assert resp2["success"] is True, str(resp2)
