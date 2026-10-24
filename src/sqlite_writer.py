import logging
import os
import queue
import sqlite3
import threading
from typing import Callable, Sequence


class SqliteWriter:
    def __init__(
        self,
        db_path,
        *,
        pragmas: Sequence[str] = (),
        maxsize: int = 0,
        low_priority: bool = False,
        timeout: float = 30.0,
        name: str = "SqliteWriter",
    ):
        self.db_path = str(db_path)
        self._pragmas = tuple(pragmas)
        self._low_priority = low_priority
        self._conn_timeout = timeout
        self._local = threading.local()
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self._running = threading.Event()
        self._running.set()
        self._log = logging.getLogger(name)
        self._thread = threading.Thread(target=self._worker, name=name, daemon=True)
        self._thread.start()


    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=self._conn_timeout)
            conn.row_factory = sqlite3.Row
            for pragma in self._pragmas:
                try:
                    conn.execute(pragma)
                except sqlite3.OperationalError as e:
                    self._log.warning(f"pragma {pragma!r} failed: {e}")
            self._local.conn = conn
        return conn

    def _close_local(self):
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


    def _worker(self):
        if self._low_priority and hasattr(os, "nice"):
            try:
                os.nice(19)
            except OSError:
                pass
        while self._running.is_set():
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                self._queue.task_done()
                break
            fn, result_q = item
            try:
                result = fn()
                if result_q is not None:
                    result_q.put(("ok", result))
            except Exception as e:  # noqa: BLE001 - carried to the caller or logged
                if result_q is not None:
                    result_q.put(("err", e))
                else:
                    self._log.error(f"write failed: {e}")
            finally:
                self._queue.task_done()
        self._close_local()


    def submit(self, fn: Callable, timeout: float = 30.0):
        result_q: queue.Queue = queue.Queue()
        self._queue.put((fn, result_q))
        status, payload = result_q.get(timeout=timeout)
        if status == "err":
            raise payload
        return payload

    def submit_nowait(self, fn: Callable) -> bool:
        try:
            self._queue.put_nowait((fn, None))
            return True
        except queue.Full:
            return False


    def flush(self):
        self._queue.join()

    def close(self):
        self._running.clear()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=5.0)
        self._close_local()
