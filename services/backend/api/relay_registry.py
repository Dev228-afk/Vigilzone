import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class RelayHandle:
    camera_id: int
    process: subprocess.Popen
    stop_requested: bool = False
    stderr_tail: deque[str] = field(default_factory=lambda: deque(maxlen=120))


class RelayRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handles: dict[int, RelayHandle] = {}

    def is_running(self, camera_id: int) -> bool:
        with self._lock:
            h = self._handles.get(camera_id)
            return bool(h and h.process.poll() is None)

    def pid(self, camera_id: int) -> int | None:
        with self._lock:
            h = self._handles.get(camera_id)
            if not h:
                return None
            return h.process.pid

    def start(
        self,
        *,
        camera_id: int,
        command: list[str],
        on_exit: Callable[[int, int, str, bool], None] | None = None,
    ) -> int:
        with self._lock:
            existing = self._handles.get(camera_id)
            if existing and existing.process.poll() is None:
                raise RuntimeError("Relay already running")

            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            handle = RelayHandle(camera_id=camera_id, process=process)
            self._handles[camera_id] = handle

        watcher = threading.Thread(
            target=self._watch_process,
            args=(handle, on_exit),
            daemon=True,
            name=f"relay-watch-{camera_id}",
        )
        watcher.start()
        return process.pid

    def stop(self, camera_id: int, timeout_s: float = 10.0) -> bool:
        with self._lock:
            handle = self._handles.get(camera_id)
        if not handle:
            return False

        handle.stop_requested = True
        process = handle.process
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        return True

    def _watch_process(
        self,
        handle: RelayHandle,
        on_exit: Callable[[int, int, str, bool], None] | None,
    ) -> None:
        process = handle.process
        if process.stderr is not None:
            for line in process.stderr:
                s = line.strip()
                if s:
                    handle.stderr_tail.append(s)

        exit_code = process.wait()
        stderr_tail = "\n".join(handle.stderr_tail)[-4000:]

        with self._lock:
            self._handles.pop(handle.camera_id, None)

        if on_exit:
            on_exit(handle.camera_id, exit_code, stderr_tail, handle.stop_requested)


RELAY_REGISTRY = RelayRegistry()
