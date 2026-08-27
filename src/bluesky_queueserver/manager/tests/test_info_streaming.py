import pprint
import threading
import time as ttime

import pytest

from bluesky_queueserver.manager.output_streaming import ReceiveSystemInfo, _default_zmq_info_topic

from .common import (
    _user,
    _user_group,
    append_code_to_last_startup_file,
    condition_environment_closed,
    condition_environment_created,
    condition_queue_processing_finished,
    copy_default_profile_collection,
    re_manager_cmd,  # noqa: F401
    use_zmq_encoding_for_tests,
    wait_for_condition,
    zmq_request,
)

timeout_env_open = 10


class ReceiveMessages(threading.Thread):
    def __init__(self, *, receiver_class, zmq_subscribe_addr, zmq_topic, encoding, timeout=0.1):
        super().__init__()
        self._rco = receiver_class(zmq_subscribe_addr=zmq_subscribe_addr, zmq_topic=zmq_topic, encoding=encoding)
        self._exit = False
        self.received_msgs = []
        self._timeout = timeout
        self.n_timeouts = 0

    def run(self):
        while True:
            try:
                _ = {} if (self._timeout is None) else {"timeout": self._timeout}
                msg = self._rco.recv(**_)
                self.received_msgs.append(msg)
            except TimeoutError:
                self.n_timeouts += 1
            if self._exit:
                break

    def stop(self):
        self._exit = True

    def subscribe(self):
        self._rco.subscribe()

    def unsubscribe(self):
        self._rco.unsubscribe()

    def filter_msgs(self, key):
        """
        Returns a list of messages of the specific type (with matching key).
        """
        return [_ for _ in self.received_msgs if key in _["msg"].keys()]


# fmt: off
@pytest.mark.parametrize("stream_enabled", [True, False, None])
# fmt: on
def test_zmq_info_streaming_1(monkeypatch, re_manager_cmd, stream_enabled):  # noqa: F811
    """
    Test 0MQ streaming functionality: streaming of status messages.
    Test periodic streaming (once per second).
    Test that streamed status reflect current state of RE Manager.
    Test that streaming can be disabled.
    """
    address_info_server = "tcp://*:60621"
    address_info_client = "tcp://localhost:60621"

    params_server = [f"--zmq-info-addr={address_info_server}"]
    if stream_enabled is not None:
        params_server.append(f"--zmq-publish-info={'ON' if stream_enabled else 'OFF'}")


    zmq_encoding = use_zmq_encoding_for_tests()

    rm_info = ReceiveMessages(
        receiver_class=ReceiveSystemInfo,
        zmq_subscribe_addr=address_info_client,
        zmq_topic=_default_zmq_info_topic,
        encoding=zmq_encoding,
    )

    rm_info.start()

    re_manager_cmd(params_server)

    # Test periodic streaming of status messages (once per second)
    if stream_enabled is True:
        ttime.sleep(6)
        assert len(rm_info.received_msgs) > 5

        msg_prev = rm_info.received_msgs[-2]
        msg_last = rm_info.received_msgs[-1]
        assert msg_last["time"] > msg_prev["time"]
        status_prev = msg_prev["msg"]["status"]
        status_last = msg_last["msg"]["status"]
        assert status_last["status_uid"] == status_prev["status_uid"]
        assert status_last["manager_state"] == "idle"
        assert status_last["worker_environment_exists"] is False

    zmq_request("environment_open")
    assert wait_for_condition(time=timeout_env_open, condition=condition_environment_created)

    # The assumption is that only 'status' messages are streamed.
    # If other messages are streamed, then the test needs to be adjusted.
    if stream_enabled is True:
        status_1 = rm_info.received_msgs[-1]["msg"]["status"]
        assert status_1["worker_environment_exists"] is True

    zmq_request("environment_close")
    assert wait_for_condition(time=3, condition=condition_environment_closed)

    if stream_enabled is True:
        status_2 = rm_info.received_msgs[-1]["msg"]["status"]
        assert status_2["worker_environment_exists"] is False
        assert status_2["status_uid"] != status_1["status_uid"]

    if stream_enabled is not True:
        assert len(rm_info.received_msgs) == 0

    rm_info.stop()
    rm_info.join()


_script_device_progress = """

from ophyd_async import sim
from ophyd_async.core import init_devices

with init_devices():
    sim_motor = sim.SimMotor(name="sim_motor", instant=False)
"""


# fmt: off
@pytest.mark.parametrize("stream_dev_progress_enabled", [True, False, None])
# fmt: on
def test_zmq_info_streaming_2(tmp_path, monkeypatch, re_manager_cmd, stream_dev_progress_enabled):  # noqa: F811
    """
    Test 0MQ streaming functionality: streaming of device progress.
    Test that streaming of device progress can be disabled.
    """

    pc_path = copy_default_profile_collection(tmp_path)

    # Add extra plan. The original set of startup files will not contain this plan.
    append_code_to_last_startup_file(pc_path, additional_code=_script_device_progress)

    address_info_server = "tcp://*:60621"
    address_info_client = "tcp://localhost:60621"

    params_server = [f"--zmq-info-addr={address_info_server}", "--zmq-publish-info=ON", f"--startup-dir={pc_path}"]
    if stream_dev_progress_enabled is not None:
        params_server.append(f"--zmq-stream-device-progress={'ON' if stream_dev_progress_enabled else 'OFF'}")

    zmq_encoding = use_zmq_encoding_for_tests()

    rm_info = ReceiveMessages(
        receiver_class=ReceiveSystemInfo,
        zmq_subscribe_addr=address_info_client,
        zmq_topic=_default_zmq_info_topic,
        encoding=zmq_encoding,
    )
    msg_key = "device_progress"

    rm_info.start()

    re_manager_cmd(params_server)

    msgs = rm_info.filter_msgs(msg_key)
    assert len(msgs) == 0

    zmq_request("environment_open")
    assert wait_for_condition(time=timeout_env_open, condition=condition_environment_created)

    _plan_mv = {"name": "mv", "args": ["sim_motor", 5.0], "item_type": "plan"}
    params = {"item": _plan_mv, "user": _user, "user_group": _user_group}
    resp2, _ = zmq_request("queue_item_add", params)
    assert resp2["success"] is True, f"resp={resp2}"

    resp3, _ = zmq_request("queue_start")
    assert resp3["success"] is True

    assert wait_for_condition(time=60, condition=condition_queue_processing_finished)

    zmq_request("environment_close")
    assert wait_for_condition(time=3, condition=condition_environment_closed)

    msgs = rm_info.filter_msgs(msg_key)
    print(f"msgs = {pprint.pformat(msgs)}")
    if stream_dev_progress_enabled is True:
        assert len(msgs) > 3
        assert msgs[0]["msg"]["device_progress"]["name"] == "sim_motor"
        assert msgs[0]["msg"]["device_progress"]["current"] == 0.0
        assert msgs[-2]["msg"]["device_progress"]["current"] == 5.0
        assert msgs[-1]["msg"]["device_progress"]["completed"] is True
    else:
        assert len(msgs) == 0

    rm_info.stop()
    rm_info.join()
