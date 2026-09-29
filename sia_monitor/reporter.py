"""
Envío de lecturas al servidor en segundo plano.

Las cámaras nunca esperan a la red: cada placa confirmada entra a una cola y un
hilo la envía. Si no hay internet, se reintenta con espera creciente y las
lecturas se conservan en memoria (hasta `max_pending`).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .config import CameraConfig

log = logging.getLogger(__name__)


@dataclass
class PlateRead:
    plate: str
    camera: CameraConfig
    confidence: float
    raw_text: str = ""
    at: float = field(default_factory=time.time)
    snapshot: Any = None
    """Recorte de la imagen (numpy BGR) para mostrarlo en la alerta."""


class ApiLike(Protocol):
    def report_sighting(self, plate: str, **kwargs: Any) -> dict[str, Any]: ...
    def create_detection(self, plate: str, wanted_plate_id: str | None, **kwargs: Any) -> str | None: ...


class Reporter:
    def __init__(
        self,
        api: ApiLike,
        on_result: Callable[[PlateRead, dict[str, Any]], None],
        on_status: Callable[[bool, int], None] = lambda online, pending: None,
        max_pending: int = 5000,
    ):
        self.api = api
        self.on_result = on_result
        self.on_status = on_status
        self._queue: queue.Queue[PlateRead | None] = queue.Queue(maxsize=max_pending)
        self._thread = threading.Thread(target=self._run, name="reporter", daemon=True)
        self._stop = threading.Event()
        self.online = True

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def submit(self, read: PlateRead) -> None:
        try:
            self._queue.put_nowait(read)
        except queue.Full:
            log.warning("Cola de envío llena; se descarta la lectura %s", read.plate)

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            read = self._queue.get()
            if read is None:
                break
            while not self._stop.is_set():
                try:
                    self._send(read)
                    backoff = 1.0
                    self._set_online(True)
                    break
                except Exception as error:  # red caída o error del servidor: se reintenta
                    log.warning("Error enviando %s: %s", read.plate, error)
                    self._set_online(False)
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2, 60.0)

    def _send(self, read: PlateRead) -> None:
        cam = read.camera
        common = dict(camera_name=cam.name, location_name=cam.display_location, address=cam.address,
                      latitude=cam.latitude, longitude=cam.longitude)
        result = self.api.report_sighting(read.plate, raw_text=read.raw_text, **common)
        if result.get("found"):
            try:
                self.api.create_detection(read.plate, result.get("id"), **common)
            except Exception as error:  # la alerta local se muestra igual
                log.error("No se pudo registrar la detección de %s: %s", read.plate, error)
                result = {**result, "detectionError": str(error)}
        self.on_result(read, result)

    def _set_online(self, online: bool) -> None:
        if online != self.online:
            self.online = online
        self.on_status(online, self.pending)
