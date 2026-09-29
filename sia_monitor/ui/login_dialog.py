from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from .. import APP_NAME
from ..backend import AuthError, NewPasswordRequired, Session
from .common import resource_path


class LoginDialog(QDialog):
    """Inicio de sesión con una cuenta de Cognito del grupo `camara`."""

    def __init__(self, session: Session, username: str = "", parent=None):
        super().__init__(parent)
        self.session = session
        self.setWindowTitle(f"{APP_NAME} — Iniciar sesión")
        self.setMinimumWidth(420)

        logo = QLabel()
        logo.setPixmap(QPixmap(str(resource_path("assets/logo_dark.png"))).scaledToWidth(
            320, Qt.TransformationMode.SmoothTransformation))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("<h3>Monitor de cámaras</h3>Ingresa con la cuenta de cámaras asignada por el administrador.")
        title.setWordWrap(True)

        self.email = QLineEdit(username)
        self.email.setPlaceholderText("camaras@correo.com")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)

        self.form = QFormLayout()
        self.form.addRow("Correo", self.email)
        self.form.addRow("Contraseña", self.password)
        self.form.addRow("Nueva contraseña", self.new_password)
        self.form.addRow("Confirmar", self.confirm)
        self._show_new_password(False)

        self.error = QLabel()
        self.error.setStyleSheet("color: #f87171; font-weight: bold;")
        self.error.setWordWrap(True)

        self.button = QPushButton("Ingresar")
        self.button.setObjectName("primary")
        self.button.clicked.connect(self.submit)
        self.password.returnPressed.connect(self.submit)

        layout = QVBoxLayout(self)
        layout.addWidget(logo)
        layout.addWidget(title)
        layout.addLayout(self.form)
        layout.addWidget(self.error)
        layout.addWidget(self.button, alignment=Qt.AlignmentFlag.AlignRight)
        if username:
            self.password.setFocus()

    def _show_new_password(self, visible: bool) -> None:
        for widget in (self.new_password, self.confirm):
            self.form.setRowVisible(widget, visible)
        self.email.setEnabled(not visible)
        self.password.setEnabled(not visible)

    def submit(self) -> None:
        self.error.clear()
        self.button.setEnabled(False)
        try:
            if self.new_password.isVisible():
                if self.new_password.text() != self.confirm.text():
                    raise AuthError("Las contraseñas no coinciden.")
                self.session.set_new_password(self.new_password.text())
            else:
                self.session.login(self.email.text(), self.password.text())
            self.accept()
        except NewPasswordRequired as info:
            self.error.setText(str(info))
            self._show_new_password(True)
            self.button.setText("Guardar contraseña")
        except AuthError as error:
            self.error.setText(str(error))
        finally:
            self.button.setEnabled(True)
