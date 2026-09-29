from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtGui import QImage, QPixmap

STYLE = """
QMainWindow, QDialog { background: #0b1220; color: #e2e8f0; }
QLabel { color: #e2e8f0; }
QLineEdit, QDoubleSpinBox, QSpinBox {
    background: #1e293b; color: #f8fafc; border: 1px solid #334155; border-radius: 6px; padding: 6px;
}
QPushButton {
    background: #1e293b; color: #f8fafc; border: 1px solid #334155; border-radius: 6px; padding: 7px 14px;
}
QPushButton:hover { border-color: #0f66ff; }
QPushButton#primary { background: #0f66ff; border-color: #0f66ff; font-weight: bold; }
QToolBar { background: #0f172a; border: none; spacing: 6px; padding: 4px; }
QToolButton { color: #f8fafc; padding: 6px 10px; border-radius: 6px; }
QToolButton:hover { background: #1e293b; }
QStatusBar { background: #0f172a; color: #94a3b8; }
QListWidget { background: #0f172a; color: #e2e8f0; border: 1px solid #1e293b; border-radius: 8px; }
QCheckBox { color: #e2e8f0; }
QDockWidget { color: #e2e8f0; }
"""


def resource_path(relative: str) -> Path:
    """Ruta a un archivo incluido en el programa (funciona también empaquetado con PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / relative


def bgr_to_pixmap(frame: np.ndarray, max_width: int, max_height: int) -> QPixmap:
    h, w = frame.shape[:2]
    scale = min(max_width / w, max_height / h, 1.0)
    if scale < 1.0:
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    height, width = rgb.shape[:2]
    image = QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(image.copy())
