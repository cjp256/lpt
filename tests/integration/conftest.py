import logging
import os


# content of conftest.py
def pytest_configure(config):
    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    if worker_id is not None:
        logging.basicConfig(
            filename=f"/tmp/lpt-tests/tests_{worker_id}.log",
            level=logging.DEBUG,
        )
