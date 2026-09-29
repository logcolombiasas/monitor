from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from ..camera import open_source
from ..config import CameraConfig
from ..geo import format_coordinates, parse_coordinates
from .common import bgr_to_pixmap

SOURCE_HELP = (
    "<b>Ejemplos de fuente:</b><br>"
    "• Cámara IP / NVR Hikvision: <code>rtsp://usuario:clave@IP:554/Streaming/Channels/101</code><br>"
    "• Dahua / Imou: <code>rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&amp;subtype=0</code><br>"
    "• Webcam o capturadora USB: <code>0</code>, <code>1</code>…<br>"
    "• Archivo de video para pruebas: <code>C:\\videos\\prueba.mp4</code>"
)


class _Probe(QObject):
    done = Signal(object, str)


class CameraDialog(QDialog):
    """Agregar o editar una cámara, con prueba de conexión."""

    def __init__(self, camera: CameraConfig | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar cámara" if camera else "Agregar cámara")
        self.setMinimumWidth(560)
        self._camera = camera

        self.name = QLineEdit(camera.name if camera else "")
        self.name.setPlaceholderText("Entrada principal")
        self.source = QLineEdit(camera.source if camera else "")
        self.source.setPlaceholderText("rtsp://usuario:clave@192.168.1.64:554/Streaming/Channels/101")
        self.location = QLineEdit(camera.location_name if camera else "")
        self.location.setPlaceholderText("Parqueadero Calle 80")
        self.address = QLineEdit(camera.address if camera else "")
        self.address.setPlaceholderText("Calle 80 # 15-20, Bogotá")
        self.coordinates = QLineEdit(format_coordinates(camera.latitude, camera.longitude) if camera else "")
        self.coordinates.setPlaceholderText("4.686000, -74.056000  (pega aquí las coordenadas de Google Maps)")
        self.coordinates.textChanged.connect(self._validate_coordinates)
        self.coordinates_hint = QLabel()
        self.coordinates_hint.setWordWrap(True)
        self.coordinates_hint.setStyleSheet("font-size: 12px;")
        view_map = QPushButton("Ver en mapa")
        view_map.clicked.connect(self._open_map)
        self.enabled = QCheckBox("Cámara activa")
        self.enabled.setChecked(camera.enabled if camera else True)

        coords = QHBoxLayout()
        coords.addWidget(self.coordinates, 1)
        coords.addWidget(view_map)

        form = QFormLayout()
        form.addRow("Nombre", self.name)
        form.addRow("Fuente de video", self.source)
        form.addRow("Lugar (sector)", self.location)
        form.addRow("Dirección exacta", self.address)
        form.addRow("Coordenadas *", coords)
        form.addRow("", self.coordinates_hint)
        form.addRow("", self.enabled)

        help_label = QLabel(SOURCE_HELP)
        help_label.setWordWrap(True)
        help_label.setTextFormat(Qt.TextFormat.RichText)
        help_label.setStyleSheet("color: #94a3b8; font-size: 12px;")

        self.preview = QLabel("Usa \"Probar conexión\" para ver una imagen de la cámara.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(200)
        self.preview.setStyleSheet("background: #000; border-radius: 8px; color: #94a3b8;")

        test = QPushButton("Probar conexión")
        test.clicked.connect(self.probe)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)

        self.error = QLabel()
        self.error.setStyleSheet("color: #f87171;")

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(help_label)
        layout.addWidget(test, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.preview)
        layout.addWidget(self.error)
        layout.addWidget(self.buttons)

        self._validate_coordinates()
        self._probe = _Probe()
        self._probe.done.connect(self._on_probe)
        self.result_camera: CameraConfig | None = None

    def probe(self) -> None:
        source = self.source.text().strip()
        if not source:
            return
        self.preview.setText("Conectando…")

        def run():
            cap = open_source(source)
            ok, frame = cap.read() if cap.isOpened() else (False, None)
            cap.release()
            self._probe.done.emit(frame if ok else None, "" if ok else "No se pudo leer video de esa fuente.")

        threading.Thread(target=run, daemon=True).start()

    def _on_probe(self, frame, message: str) -> None:
        if frame is None:
            self.preview.setText(message)
            return
        self.preview.setPixmap(bgr_to_pixmap(frame, 520, 280))

    def _validate_coordinates(self) -> None:
        parsed = parse_coordinates(self.coordinates.text())
        if parsed:
            self.coordinates_hint.setText(f"✔ Latitud {parsed[0]:.6f} · Longitud {parsed[1]:.6f}")
            self.coordinates_hint.setStyleSheet("color: #4ade80; font-size: 12px;")
        else:
            self.coordinates_hint.setText(
                "En Google Maps: clic derecho sobre el punto exacto de la cámara → clic en las coordenadas para "
                "copiarlas → pégalas aquí.")
            self.coordinates_hint.setStyleSheet("color: #A7A9AC; font-size: 12px;")

    def _open_map(self) -> None:
        parsed = parse_coordinates(self.coordinates.text())
        url = f"https://www.google.com/maps?q={parsed[0]},{parsed[1]}" if parsed else "https://www.google.com/maps"
        QDesktopServices.openUrl(QUrl(url))

    def save(self) -> None:
        if not self.name.text().strip() or not self.source.text().strip():
            self.error.setText("Nombre y fuente de video son obligatorios.")
            return
        parsed = parse_coordinates(self.coordinates.text())
        if not parsed:
            self.error.setText("Las coordenadas son obligatorias: cada lectura se guarda con la ubicación exacta "
                               "de la cámara (ej. 4.686000, -74.056000).")
            return
        lat, lng = parsed
        values = dict(
            name=self.name.text().strip(),
            source=self.source.text().strip(),
            location_name=self.location.text().strip(),
            address=self.address.text().strip(),
            latitude=lat,
            longitude=lng,
            enabled=self.enabled.isChecked(),
        )
        self.result_camera = CameraConfig(id=self._camera.id, **values) if self._camera else CameraConfig(**values)
        self.accept()
