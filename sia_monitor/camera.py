"""
Lectura de una cámara y análisis de placas.

Cada cámara usa dos hilos:
  - Lector: toma cuadros del stream sin parar y guarda solo el último
    (así el video RTSP no se atrasa aunque el análisis sea más lento).
  - Analizador: cada 1/analyze_fps segundos pasa el último cuadro al motor ALPR,
    confirma las placas con PlateTracker y entrega las confirmadas.
Si el stream se cae, se reconecta solo con espera creciente.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

import cv2
import numpy as np

from .config import CameraConfig
from .engine import Detection, PlateEngine
from .reporter import PlateRead
from .tracker import PlateTracker

log = logging.getLogger(__name__)

# RTSP por TCP: más estable en internet que UDP (menos cuadros corruptos)
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;10000000")


class CameraState(str, Enum):
    CONNECTING = "Conectando"
    LIVE = "En vivo"
    RECONNECTING = "Reconectando"
    STOPPED = "Detenida"


@dataclass
class FrameUpdate:
    camera_id: str
    frame: np.ndarray
    detections: list[Detection]


def open_source(source: str) -> cv2.VideoCapture:
    """Número = webcam USB; cualquier otra cosa = URL (rtsp/http) o archivo de video."""
    src = source.strip()
    if src.isdigit():
        cap = cv2.VideoCapture(int(src))
    else:
        cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def is_file_source(source: str) -> bool:
    return os.path.isfile(source.strip())


class CameraWorker:
    def __init__(
        self,
        camera: CameraConfig,
        engine: PlateEngine,
        on_read: Callable[[PlateRead], None],
        on_frame: Callable[[FrameUpdate], None] = lambda update: None,
        on_state: Callable[[str, CameraState, str], None] = lambda cid, state, msg: None,
        analyze_fps: float = 4.0,
        cooldown_s: float = 600.0,
        min_confidence: float = 0.6,
    ):
        self.camera = camera
        self.engine = engine
        self.on_read = on_read
        self.on_frame = on_frame
        self.on_state = on_state
        self.analyze_interval = 1.0 / max(analyze_fps, 0.2)
        self.min_confidence = min_confidence
        self.tracker = PlateTracker(min_hits=2, window_s=3.0, cooldown_s=cooldown_s)
        self._stop = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest: np.ndarray | None = None
        self._latest_id = 0
        self._last_detections: list[Detection] = []
        self.state = CameraState.CONNECTING
        self._threads = [
            threading.Thread(target=self._read_loop, name=f"read-{camera.id}", daemon=True),
            threading.Thread(target=self._analyze_loop, name=f"alpr-{camera.id}", daemon=True),
        ]

    def start(self) -> None:
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float = 3.0) -> None:
        for t in self._threads:
            t.join(timeout)

    def latest(self) -> tuple[np.ndarray | None, int, list[Detection]]:
        """Último cuadro recibido (para mostrarlo en pantalla) y las últimas placas detectadas."""
        with self._frame_lock:
            return self._latest, self._latest_id, self._last_detections

    def _set_state(self, state: CameraState, message: str = "") -> None:
        self.state = state
        self.on_state(self.camera.id, state, message)

    # --- Lectura del stream -------------------------------------------------

    def _read_loop(self) -> None:
        backoff = 2.0
        state = CameraState.CONNECTING
        while not self._stop.is_set():
            self._set_state(state)
            cap = open_source(self.camera.source)
            if not cap.isOpened():
                cap.release()
                self._set_state(CameraState.RECONNECTING, "No fue posible abrir la cámara")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 60.0)
                state = CameraState.RECONNECTING
                continue

            backoff = 2.0
            self._set_state(CameraState.LIVE)
            file_source = is_file_source(self.camera.source)
            frame_delay = 1.0 / (cap.get(cv2.CAP_PROP_FPS) or 25.0) if file_source else 0.0
            failures = 0
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    if file_source:  # video de prueba: vuelve a empezar
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    failures += 1
                    if failures > 25:
                        break
                    time.sleep(0.04)
                    continue
                failures = 0
                with self._frame_lock:
                    self._latest = frame
                    self._latest_id += 1
                if frame_delay:
                    time.sleep(frame_delay)
            cap.release()
            if not self._stop.is_set():
                self._set_state(CameraState.RECONNECTING, "Se perdió la señal")
                state = CameraState.RECONNECTING
                self._stop.wait(backoff)
        self._set_state(CameraState.STOPPED)

    # --- Análisis -----------------------------------------------------------

    def _analyze_loop(self) -> None:
        last_id = 0
        while not self._stop.is_set():
            started = time.monotonic()
            with self._frame_lock:
                frame, frame_id = self._latest, self._latest_id
            if frame is not None and frame_id != last_id:
                last_id = frame_id
                try:
                    self.process(frame)
                except Exception:  # un cuadro dañado no debe detener la cámara
                    log.exception("Error analizando cámara %s", self.camera.name)
            elapsed = time.monotonic() - started
            self._stop.wait(max(0.0, self.analyze_interval - elapsed))

    def process(self, frame: np.ndarray, now: float | None = None) -> list[str]:
        """Analiza un cuadro; devuelve las placas confirmadas (también usado en pruebas)."""
        detections = self.engine.detect(frame)
        with self._frame_lock:
            self._last_detections = detections
        self.on_frame(FrameUpdate(self.camera.id, frame, detections))

        valid = [d for d in detections if d.plate and d.confidence >= self.min_confidence]
        confirmed = self.tracker.push([d.plate for d in valid], now=now)  # type: ignore[misc]
        for plate in confirmed:
            best = max((d for d in valid if d.plate == plate), key=lambda d: d.confidence)
            x1, y1, x2, y2 = best.box
            snapshot = frame[max(y1, 0):max(y2, 0), max(x1, 0):max(x2, 0)].copy()
            self.on_read(PlateRead(
                plate=plate,
                camera=self.camera,
                confidence=best.confidence,
                raw_text=best.raw_text,
                snapshot=snapshot,
            ))
        return confirmed
