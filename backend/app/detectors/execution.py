"""Concurrent detector execution inside the isolated document worker."""

from concurrent.futures import Future, wait
import os
from threading import Thread


def detector_timeout() -> float:
    return float(os.environ.get("KAVACH_DETECTOR_TIMEOUT_SECONDS", "5"))


def run_detectors(calls, timeout: float):
    """Return completed results and errors in input order at the deadline.

    A timed-out native call can continue until the enclosing job worker exits.
    Daemon threads keep that call from blocking publication of other evidence.
    """
    def invoke(call, future):
        try:
            future.set_result(call())
        except Exception as error:
            future.set_exception(error)

    futures = []
    for call in calls:
        future = Future()
        futures.append(future)
        Thread(target=invoke, args=(call, future), daemon=True).start()
    done, _ = wait(futures, timeout=timeout)
    results = []
    for future in futures:
        if future not in done:
            results.append(TimeoutError(f"detector exceeded {timeout:g}s"))
        elif future.exception() is not None:
            results.append(future.exception())
        else:
            results.append(future.result())
    return results
