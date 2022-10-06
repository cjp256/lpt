import datetime
import logging

logger = logging.getLogger("lpt.time")


def calculate_reference_timestamp(
    timestamp: datetime.datetime, monotonic_time: float
) -> datetime.datetime:
    """Determine timestmap for monotonic time 0."""
    return timestamp - datetime.timedelta(seconds=monotonic_time)
