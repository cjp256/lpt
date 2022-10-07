import datetime

from lpt import cloudinit


def test_start_event():
    data = "2022-10-07 11:47:53,209 - handlers.py[DEBUG]: start: azure-ds/_get_data: _get_data"

    entry = cloudinit.CloudInitEntry.parse(data)

    assert entry == cloudinit.CloudInitEntry(
        data="2022-10-07 11:47:53,209 - handlers.py[DEBUG]: start: azure-ds/_get_data: _get_data",
        log_level="DEBUG",
        message="_get_data",
        module="handlers.py",
        result=None,
        timestamp_realtime=datetime.datetime(2022, 10, 7, 11, 47, 53, 209000),
        timestamp_monotonic=0.0,
        event_type="start",
        stage="azure-ds/_get_data",
    )


def test_finish_event():
    data = "2022-10-07 11:51:25,375 - handlers.py[DEBUG]: finish: azure-ds/_get_data: SUCCESS: _get_data"

    entry = cloudinit.CloudInitEntry.parse(data)

    assert entry == cloudinit.CloudInitEntry(
        data="2022-10-07 11:51:25,375 - handlers.py[DEBUG]: finish: azure-ds/_get_data: SUCCESS: _get_data",
        log_level="DEBUG",
        message="_get_data",
        module="handlers.py",
        result="SUCCESS",
        timestamp_realtime=datetime.datetime(2022, 10, 7, 11, 51, 25, 375000),
        timestamp_monotonic=0.0,
        event_type="finish",
        stage="azure-ds/_get_data",
    )


def test_log():
    data = "2022-10-03 20:36:23,366 - main.py[DEBUG]: Closing stdin."

    entry = cloudinit.CloudInitEntry.parse(data)

    assert entry == cloudinit.CloudInitEntry(
        data="2022-10-03 20:36:23,366 - main.py[DEBUG]: Closing stdin.",
        log_level="DEBUG",
        message="Closing stdin.",
        module="main.py",
        result=None,
        timestamp_realtime=datetime.datetime(2022, 10, 3, 20, 36, 23, 366000),
        timestamp_monotonic=0.0,
        event_type="log",
        stage=None,
    )


def test_reference_point():
    data = "2022-10-03 20:36:23,366 - util.py[DEBUG]: Cloud-init v. 22.2-0ubuntu1~20.04.3 running 'init-local' at Mon, 03 Oct 2022 20:36:23 +0000. Up 20497.78 seconds."

    entry = cloudinit.CloudInitEntry.parse(data)

    assert entry == cloudinit.CloudInitEntry(
        data="2022-10-03 20:36:23,366 - util.py[DEBUG]: Cloud-init v. 22.2-0ubuntu1~20.04.3 running 'init-local' at Mon, 03 Oct 2022 20:36:23 +0000. Up 20497.78 seconds.",
        log_level="DEBUG",
        message="Cloud-init v. 22.2-0ubuntu1~20.04.3 running 'init-local' at Mon, 03 Oct 2022 20:36:23 +0000. Up 20497.78 seconds.",
        module="util.py",
        result=None,
        timestamp_realtime=datetime.datetime(2022, 10, 3, 20, 36, 23, 366000),
        timestamp_monotonic=20497.78,
        event_type="log",
        stage=None,
    )
