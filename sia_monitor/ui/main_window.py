from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (
    QDockWidget, QGridLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from ..camera import CameraState, CameraWorker
from ..config import AppConfig, CameraConfig
from ..engine import PlateEngine
from ..plates import format_plate
from ..reporter import PlateRead, Reporter
from .camera_dialog import CameraDialog
from .common import bgr_to_pixmap, resource_path
from .tile import CameraTile

log = logging.getLogger(__name__)

MAX_RECENT = 200
MAX_ALERTS = 100


class Bus(QObject):
    """Lleva los eventos de los hilos de cámaras/red al hilo de la interfaz."""

    state = Signal(str, object, str)
    result = Signal(object, object)
    network = Signal(bool, int)
    engine_ready = Signal(object, str)


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, api: Any, username: str, offline: bool = False):
        super().__init__()
        self.config = config
        self.username = username
        self.offline = offline
        self.setWindowTitle(f"{APP_NAME} {__version__}" + (" — SIN SERVIDOR (prueba)" if offline else ""))
        self.resize(1400, 850)

        self.bus = Bus()
        self.bus.state.connect(self._on_state)
        self.bus.result.connect(self._on_result)
        self.bus.network.connect(self._on_network)
        self.bus.engine_ready.connect(self._on_engine_ready)

        self.engine: PlateEngine | None = None
        self.workers: dict[str, CameraWorker] = {}
        self.tiles: dict[str, CameraTile] = {}

        self.reporter = Reporter(
            api,
            on_result=lambda read, res: self.bus.result.emit(read, res),
            on_status=lambda online, pending: self.bus.network.emit(online, pending),
        )
        self.reporter.start()

        self._build_ui()
        self._load_sound()
        self._start_engine()

        self._render = QTimer(self)
        self._render.timeout.connect(self._render_frames)
        self._render.start(80)  # ~12 cuadros/s en pantalla

    # --- Construcción de la interfaz ------------------------------------------

    def _build_ui(self) -> None:
        toolbar = self.addToolBar("Principal")
        toolbar.setMovable(False)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(resource_path("assets/logo_dark.png"))).scaledToHeight(
            40, Qt.TransformationMode.SmoothTransformation))
        logo.setContentsMargins(6, 0, 18, 0)
        toolbar.addWidget(logo)
        add = QAction("➕ Agregar cámara", self)
        add.triggered.connect(self.add_camera)
        toolbar.addAction(add)
        self.sound_action = QAction("🔔 Sonido", self, checkable=True, checked=self.config.sound)
        self.sound_action.toggled.connect(self._toggle_sound)
        toolbar.addAction(self.sound_action)
        clear = QAction("🧹 Limpiar alertas", self)
        clear.triggered.connect(lambda: self.alerts.clear())
        toolbar.addAction(clear)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(8)
        self.empty = QLabel(
            "<h2>Sin cámaras</h2>Usa <b>➕ Agregar cámara</b> para conectar cámaras IP (RTSP), "
            "canales de un DVR/NVR o webcams USB."
        )
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(self.grid_host)

        # Panel lateral: alertas y lecturas recientes
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(QLabel("<b style='color:#ED1C24'>🚨 Vehículos del listado</b>"))
        self.alerts = QListWidget()
        self.alerts.setIconSize(self.alerts.iconSize() * 3)
        side_layout.addWidget(self.alerts, 2)
        side_layout.addWidget(QLabel("<b>Lecturas recientes</b>"))
        self.recent = QListWidget()
        side_layout.addWidget(self.recent, 3)
        dock = QDockWidget("Alertas y lecturas", self)
        dock.setWidget(side)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        dock.setMinimumWidth(340)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self.net_label = QLabel()
        self.engine_label = QLabel("⏳ Cargando modelos de reconocimiento…")
        self.statusBar().addWidget(self.engine_label)
        self.statusBar().addPermanentWidget(self.net_label)
        self.statusBar().addPermanentWidget(QLabel(f"👤 {self.username}"))
        self._on_network(True, 0)

        self.tray = QSystemTrayIcon(QIcon(str(resource_path("assets/icon.png"))), self)
        self.tray.setToolTip(APP_NAME)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

        self._rebuild_grid()

    def _load_sound(self) -> None:
        self.sound = QSoundEffect(self)
        self.sound.setSource(QUrl.fromLocalFile(str(resource_path("assets/alarm.wav"))))
        self.sound.setVolume(0.9)

    def _toggle_sound(self, on: bool) -> None:
        self.config.sound = on
        self.config.save()

    # --- Motor y cámaras ------------------------------------------------------

    def _start_engine(self) -> None:
        def load():
            try:
                self.bus.engine_ready.emit(PlateEngine(), "")
            except Exception as error:
                log.exception("No se pudo cargar el motor ALPR")
                self.bus.engine_ready.emit(None, str(error))

        threading.Thread(target=load, daemon=True).start()

    def _on_engine_ready(self, engine: PlateEngine | None, error: str) -> None:
        if engine is None:
            self.engine_label.setText("❌ Error cargando el reconocimiento de placas")
            QMessageBox.critical(self, APP_NAME, f"No se pudieron cargar los modelos de reconocimiento.\n\n{error}\n\n"
                                                 "La primera vez se necesita internet para descargarlos.")
            return
        self.engine = engine
        self.engine_label.setText("✅ Reconocimiento de placas activo")
        for camera in self.config.cameras:
            self._start_worker(camera)

    def _start_worker(self, camera: CameraConfig) -> None:
        if not self.engine or not camera.enabled or camera.id in self.workers:
            return
        worker = CameraWorker(
            camera,
            self.engine,
            on_read=self._on_read,
            on_state=lambda cid, state, msg: self.bus.state.emit(cid, state, msg),
            analyze_fps=self.config.analyze_fps,
            cooldown_s=self.config.cooldown_minutes * 60,
            min_confidence=self.config.min_confidence,
        )
        self.workers[camera.id] = worker
        worker.start()

    def _stop_worker(self, camera_id: str) -> None:
        worker = self.workers.pop(camera_id, None)
        if worker:
            worker.stop()

    def _on_read(self, read: PlateRead) -> None:
        """Hilo de la cámara: la placa confirmada va a la cola de envío."""
        self.reporter.submit(read)

    # --- Cuadrícula -----------------------------------------------------------

    def _rebuild_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() and item.widget() is not self.empty:
                item.widget().setParent(None)
        self.tiles = {}
        cameras = self.config.cameras
        if not cameras:
            self.grid.addWidget(self.empty, 0, 0)
            self.empty.show()
            return
        self.empty.hide()
        cols = max(1, math.ceil(math.sqrt(len(cameras))))
        for index, camera in enumerate(cameras):
            tile = CameraTile(camera)
            tile.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tile.customContextMenuRequested.connect(lambda pos, cid=camera.id: self._tile_menu(cid))
            tile.double_clicked.connect(self.edit_camera)
            if not camera.enabled:
                tile.set_state(CameraState.STOPPED, "Cámara desactivada")
            elif camera.id in self.workers:
                tile.set_state(self.workers[camera.id].state, "")
            self.tiles[camera.id] = tile
            self.grid.addWidget(tile, index // cols, index % cols)

    def _render_frames(self) -> None:
        for camera_id, worker in list(self.workers.items()):
            tile = self.tiles.get(camera_id)
            if not tile or not tile.isVisible():
                continue
            frame, frame_id, detections = worker.latest()
            if frame is not None:
                tile.show_frame(frame, frame_id, detections)

    def _tile_menu(self, camera_id: str) -> None:
        menu = QMenu(self)
        menu.addAction("✏️ Editar", lambda: self.edit_camera(camera_id))
        menu.addAction("🗑️ Eliminar", lambda: self.delete_camera(camera_id))
        menu.exec(self.cursor().pos())

    def add_camera(self) -> None:
        dialog = CameraDialog(parent=self)
        if dialog.exec() and dialog.result_camera:
            self.config.cameras.append(dialog.result_camera)
            self.config.save()
            self._rebuild_grid()
            self._start_worker(dialog.result_camera)

    def edit_camera(self, camera_id: str) -> None:
        index = next((i for i, c in enumerate(self.config.cameras) if c.id == camera_id), None)
        if index is None:
            return
        dialog = CameraDialog(self.config.cameras[index], parent=self)
        if dialog.exec() and dialog.result_camera:
            self._stop_worker(camera_id)
            self.config.cameras[index] = dialog.result_camera
            self.config.save()
            self._rebuild_grid()
            self._start_worker(dialog.result_camera)

    def delete_camera(self, camera_id: str) -> None:
        camera = next((c for c in self.config.cameras if c.id == camera_id), None)
        if not camera:
            return
        if QMessageBox.question(self, APP_NAME, f"¿Eliminar la cámara \"{camera.name}\"?") != QMessageBox.StandardButton.Yes:
            return
        self._stop_worker(camera_id)
        self.config.cameras = [c for c in self.config.cameras if c.id != camera_id]
        self.config.save()
        self._rebuild_grid()

    # --- Eventos --------------------------------------------------------------

    def _on_state(self, camera_id: str, state: CameraState, message: str) -> None:
        tile = self.tiles.get(camera_id)
        if tile:
            tile.set_state(state, message)

    def _on_network(self, online: bool, pending: int) -> None:
        if self.offline:
            self.net_label.setText("🧪 Modo prueba: sin servidor")
        elif online:
            self.net_label.setText("🟢 Conectado al servidor")
        else:
            self.net_label.setText(f"🔴 Sin conexión · {pending} lecturas pendientes")

    def _on_result(self, read: PlateRead, result: dict[str, Any]) -> None:
        when = datetime.fromtimestamp(read.at).strftime("%H:%M:%S")
        found = bool(result.get("found"))
        log.info("Placa %s · cámara %s (%s) · confianza %.2f · %s", read.plate, read.camera.name,
                 read.camera.display_location, read.confidence, "EN LISTADO" if found else "sin reporte")
        tile = self.tiles.get(read.camera.id)
        if tile:
            tile.show_read(read.plate, found, when)

        item = QListWidgetItem(f"{when}  {format_plate(read.plate)}  ·  {read.camera.name}  "
                               f"{'🚨 EN LISTADO' if found else '✓'}")
        if found:
            item.setForeground(Qt.GlobalColor.red)
        self.recent.insertItem(0, item)
        while self.recent.count() > MAX_RECENT:
            self.recent.takeItem(self.recent.count() - 1)

        if found:
            self._alert(read, result, when)

    def _alert(self, read: PlateRead, result: dict[str, Any], when: str) -> None:
        vehicle = " ".join(filter(None, [result.get("vehicleType"), result.get("brand"),
                                         result.get("line"), result.get("color")]))
        text = (f"🚨 {format_plate(read.plate)} — {read.camera.name} ({read.camera.display_location})\n"
                f"{when} · {vehicle or 'Vehículo del listado'}\n"
                f"Motivo: {result.get('reason') or '—'} · Prioridad: {result.get('priority') or '—'}")
        if result.get("detectionError"):
            text += "\n⚠️ No se pudo notificar al panel web"
        item = QListWidgetItem(text)
        item.setForeground(Qt.GlobalColor.white)
        item.setBackground(Qt.GlobalColor.darkRed)
        if read.snapshot is not None and read.snapshot.size:
            item.setIcon(QIcon(bgr_to_pixmap(read.snapshot, 160, 60)))
        self.alerts.insertItem(0, item)
        while self.alerts.count() > MAX_ALERTS:
            self.alerts.takeItem(self.alerts.count() - 1)

        if self.config.sound:
            self.sound.play()
        if self.tray.isVisible():
            self.tray.showMessage("Vehículo del listado detectado",
                                  f"{format_plate(read.plate)} en {read.camera.display_location}",
                                  QSystemTrayIcon.MessageIcon.Warning, 15000)
        QApplicationAlert.alert(self)

    def closeEvent(self, event) -> None:  # noqa: N802 (API de Qt)
        self._render.stop()
        for camera_id in list(self.workers):
            self._stop_worker(camera_id)
        self.reporter.stop()
        time.sleep(0.2)
        super().closeEvent(event)


class QApplicationAlert:
    """Hace parpadear el ícono en la barra de tareas si la ventana no está al frente."""

    @staticmethod
    def alert(widget: QWidget) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.alert(widget, 0)
