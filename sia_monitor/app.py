"""Punto de entrada: inicio de sesión y ventana de monitoreo."""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from . import APP_NAME
from .backend import Api, Session, load_backend_config
from .config import AppConfig, data_dir
from .ui.common import STYLE, resource_path
from .ui.login_dialog import LoginDialog
from .ui.main_window import MainWindow


class OfflineApi:
    """Modo prueba: lee placas sin enviarlas al servidor (para probar cámaras en sitio)."""

    def report_sighting(self, plate: str, **kwargs: Any) -> dict[str, Any]:
        return {"found": False, "plate": plate}

    def create_detection(self, plate: str, wanted_plate_id: str | None, **kwargs: Any) -> None:
        return None


def setup_logging() -> None:
    handler = RotatingFileHandler(data_dir() / "monitor.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler, logging.StreamHandler()],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sia-monitor", description=APP_NAME)
    parser.add_argument("--sin-servidor", action="store_true",
                        help="Modo prueba: muestra las placas leídas sin enviarlas al servidor.")
    args = parser.parse_args(argv)

    setup_logging()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLE)
    app.setWindowIcon(QIcon(str(resource_path("assets/icon.png"))))

    config = AppConfig.load()

    if args.sin_servidor:
        window = MainWindow(config, OfflineApi(), username="modo prueba", offline=True)
        window.show()
        return app.exec()

    try:
        backend = load_backend_config(config.amplify_outputs)
    except FileNotFoundError:
        QMessageBox.information(None, APP_NAME,
                                "Selecciona el archivo amplify_outputs.json del backend de SIA.")
        path, _ = QFileDialog.getOpenFileName(None, "amplify_outputs.json", "", "JSON (*.json)")
        if not path:
            return 1
        config.amplify_outputs = path
        config.save()
        backend = load_backend_config(path)

    session = Session(backend)
    login = LoginDialog(session, username=config.username)
    if not login.exec():
        return 0
    config.username = login.email.text().strip().lower()
    config.save()

    window = MainWindow(config, Api(session), username=session.username)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
