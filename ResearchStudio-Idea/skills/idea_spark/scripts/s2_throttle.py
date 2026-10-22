"""Machine-wide pacing for Semantic Scholar requests.

Why: S2's key tier is 1 request/s CUMULATIVE per key, and keyless is ~100 requests / 5 min. Every S2
caller used to pace itself only within its own process (or, in fetch_sections, across 15 threads that
read one unlocked timestamp), so overlapping callers — the Phase 0 search, the full-text resolver's
thread pool, paper-search's per-source worker processes — fired together and drew 429s. Same remedy as
arXiv: serialize on a lockfile in the system temp dir and hold the exclusive lock across the sleep, so
every request on this machine lands >= the interval after the previous one actually fired. flock locks
per open() call, so threads of one process queue as well. paper-search keeps an identical copy
(search_papers_by_semantic_scholar.py) on the same lockfile, since each skill is installed standalone.
"""
from __future__ import annotations
import os
import tempfile
import time

_THROTTLE_FILE = os.path.join(tempfile.gettempdir(), 'semanticscholar_throttle.lock')


def interval(keyed: bool) -> float:
    """1.1 s with a key (1 req/s plus margin), 3 s keyless; SEMANTICSCHOLAR_MIN_INTERVAL overrides the keyed value."""
    return float(os.environ.get('SEMANTICSCHOLAR_MIN_INTERVAL', '1.1')) if keyed else 3.0


def throttle(keyed: bool) -> None:
    """Block until the interval has elapsed since the last S2 request fired on this machine."""
    wait_for = interval(keyed)
    try:
        import fcntl
    except ImportError:
        time.sleep(wait_for)
        return
    fd = os.open(_THROTTLE_FILE, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        raw = os.read(fd, 64).decode('utf-8').strip()
        try:
            last = float(raw) if raw else 0.0
        except ValueError:
            last = 0.0
        wait = wait_for - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        # Stamp the moment this request is about to fire, so the next caller spaces from here.
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, str(time.time()).encode('utf-8'))
    finally:
        os.close(fd)  # releasing the fd also releases the flock
