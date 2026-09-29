from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from ..camera import CameraState
from ..config import CameraConfig
from ..engine import Detection
from ..plates import format_plate
from .common import bgr_to_pixmap

STATE_COLORS = {
    CameraState.LIVE: "#22c55e",
    CameraState.CONNECTING: "#eab308",
    CameraState.RECONNECTING: "#f97316",
    CameraState.STOPPED: "#64748b",
}


def draw_detections(frame: np.ndarray, detections: list[Detection]) -> np.ndarray:
    out = frame.copy()
    for d in detections:
        x1, y1, x2, y2 = d.box
        color = (0, 200, 0) if d.plate else (0, 200, 255)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 3)
        label = format_plate(d.plate) if d.plate else d.raw_text
        if label:
            cv2.putText(out, label, (x1, max(y1 - 8, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
    return out


class CameraTile(QFrame):
    """Una celda de la cuadrícula: video en vivo, estado y última placa leída."""

    double_clicked = Signal(str)

    def __init__(self, camera: CameraConfig):
        super().__init__()
        self.camera = camera
        self.setObjectName("tile")
        self._set_border("#242527")

        no_location = "" if camera.latitude is not None else \
            "  <span style='color:#f59e0b'>⚠ sin coordenadas: edita la cámara</span>"
        self.title = QLabel(f"<b>{camera.name}</b>  <span style='color:#94a3b8'>{camera.display_location}</span>"
                            f"{no_location}")
        self.state = QLabel()
        header = QHBoxLayout()
        header.addWidget(self.title, 1)
        header.addWidget(self.state)

        self.video = QLabel("Conectando…")
        self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video.setStyleSheet("background: #000; color: #64748b;")
        self.video.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.video.setMinimumSize(240, 135)

        self.last = QLabel("Sin lecturas")
        self.last.setStyleSheet("color: #94a3b8;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(header)
        layout.addWidget(self.video, 1)
        layout.addWidget(self.last)

        self._flash = QTimer(self)
        self._flash.setSingleShot(True)
        self._flash.timeout.connect(lambda: self._set_border("#242527"))
        self._frame_id = -1
        self.set_state(CameraState.CONNECTING, "")

    def _set_border(self, color: str) -> None:
        self.setStyleSheet(f"#tile {{ background: #121314; border: 3px solid {color}; border-radius: 10px; }}")

    def set_state(self, state: CameraState, message: str) -> None:
        color = STATE_COLORS.get(state, "#64748b")
        self.state.setText(f"<span style='color:{color}'>●</span> {state.value}")
        self.state.setToolTip(message)
        if state != CameraState.LIVE:
            self.video.setText(f"{state.value}…\n{message}")

    def show_frame(self, frame: np.ndarray, frame_id: int, detections: list[Detection]) -> None:
        if frame_id == self._frame_id:
            return
        self._frame_id = frame_id
        size = self.video.size()
        self.video.setPixmap(bgr_to_pixmap(draw_detections(frame, detections), size.width(), size.height()))

    def show_read(self, plate: str, found: bool, when: str) -> None:
        if found:
            self.last.setText(f"<b style='color:#f87171'>🚨 {format_plate(plate)} EN LISTADO</b> · {when}")
            self._set_border("#ED1C24")
            self._flash.start(15000)
        else:
            self.last.setText(f"Última: <b>{format_plate(plate)}</b> · {when}")

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (API de Qt)
        self.double_clicked.emit(self.camera.id)
        super().mouseDoubleClickEvent(event)
