"""
Conexión con el backend Amplify de SIA (el mismo del panel administrativo y la app móvil).

- Inicio de sesión con Cognito (SRP), con cuentas del grupo `camara` (o `admin`).
- Llamadas GraphQL a AppSync: `reportSighting` (verifica y guarda en el historial)
  y `createPlateDetection` (dispara la notificación al administrador).
"""

from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jwt
import requests
from pycognito import Cognito
from pycognito.exceptions import ForceChangePasswordException

from .config import data_dir

ALLOWED_GROUPS = {"camara", "admin"}


class AuthError(Exception):
    """Error de inicio de sesión con un mensaje apto para mostrar al usuario."""


class NewPasswordRequired(AuthError):
    """El usuario tiene contraseña temporal y debe definir una nueva."""


@dataclass(frozen=True)
class BackendConfig:
    region: str
    user_pool_id: str
    client_id: str
    graphql_url: str

    @classmethod
    def from_outputs(cls, outputs: dict[str, Any]) -> "BackendConfig":
        try:
            return cls(
                region=outputs["auth"]["aws_region"],
                user_pool_id=outputs["auth"]["user_pool_id"],
                client_id=outputs["auth"]["user_pool_client_id"],
                graphql_url=outputs["data"]["url"],
            )
        except KeyError as error:
            raise ValueError(f"amplify_outputs.json incompleto: falta {error}") from error


def find_amplify_outputs(configured: str = "") -> Path | None:
    """Busca amplify_outputs.json: ruta configurada, junto al .exe o en la carpeta de datos."""
    candidates = [Path(configured)] if configured else []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / "amplify_outputs.json")
        candidates.append(Path(getattr(sys, "_MEIPASS", "")) / "amplify_outputs.json")
    candidates.append(Path.cwd() / "amplify_outputs.json")
    candidates.append(data_dir() / "amplify_outputs.json")
    return next((p for p in candidates if p.is_file()), None)


def load_backend_config(configured: str = "") -> BackendConfig:
    path = find_amplify_outputs(configured)
    if not path:
        raise FileNotFoundError(
            "No se encontró amplify_outputs.json. Cópialo junto al programa o en " + str(data_dir())
        )
    return BackendConfig.from_outputs(json.loads(path.read_text(encoding="utf-8")))


class Session:
    """Sesión de Cognito con renovación automática del token."""

    RENEW_MARGIN_S = 300

    def __init__(self, config: BackendConfig):
        self.config = config
        self._cognito: Cognito | None = None
        self._pending_password: str | None = None
        self._lock = threading.Lock()

    def _client(self, username: str) -> Cognito:
        return Cognito(
            self.config.user_pool_id,
            self.config.client_id,
            user_pool_region=self.config.region,
            username=username.strip().lower(),
        )

    def login(self, username: str, password: str) -> None:
        cognito = self._client(username)
        try:
            cognito.authenticate(password=password)
        except ForceChangePasswordException as error:
            self._cognito = cognito
            self._pending_password = password
            raise NewPasswordRequired("Es el primer ingreso: define una contraseña nueva.") from error
        except Exception as error:  # botocore ClientError y errores de red
            raise AuthError(_auth_message(error)) from error
        self._set(cognito)

    def set_new_password(self, new_password: str) -> None:
        if not self._cognito or self._pending_password is None:
            raise AuthError("Vuelve a iniciar sesión.")
        try:
            self._cognito.new_password_challenge(self._pending_password, new_password)
        except Exception as error:
            raise AuthError(_auth_message(error)) from error
        self._pending_password = None
        self._set(self._cognito)

    def _set(self, cognito: Cognito) -> None:
        groups = set(self._claims(cognito.id_token).get("cognito:groups", []))
        if not groups & ALLOWED_GROUPS:
            raise AuthError("Este usuario no pertenece al grupo 'camara'. Pídele al administrador que lo agregue.")
        self._cognito = cognito

    @staticmethod
    def _claims(token: str) -> dict[str, Any]:
        return jwt.decode(token, options={"verify_signature": False})

    @property
    def username(self) -> str:
        if not self._cognito:
            return ""
        claims = self._claims(self._cognito.id_token)
        return claims.get("email") or self._cognito.username

    def token(self) -> str:
        """Token vigente para AppSync; se renueva antes de expirar."""
        with self._lock:
            if not self._cognito:
                raise AuthError("Sesión no iniciada")
            exp = self._claims(self._cognito.id_token).get("exp", 0)
            if exp - time.time() < self.RENEW_MARGIN_S:
                self._cognito.renew_access_token()
            return self._cognito.id_token

    def logout(self) -> None:
        self._cognito = None


def _auth_message(error: Exception) -> str:
    code = getattr(error, "response", {}).get("Error", {}).get("Code", "") if hasattr(error, "response") else ""
    return {
        "NotAuthorizedException": "Correo o contraseña incorrectos.",
        "UserNotFoundException": "El usuario no existe. Solicítalo al administrador.",
        "InvalidPasswordException": "La contraseña no cumple la política: mínimo 8 caracteres, "
                                    "mayúsculas, minúsculas, números y símbolos.",
        "TooManyRequestsException": "Demasiados intentos, espera unos minutos.",
        "LimitExceededException": "Demasiados intentos, espera unos minutos.",
    }.get(code, f"No fue posible iniciar sesión: {error}")


REPORT_SIGHTING = """
mutation ReportSighting($plate: String!, $latitude: Float, $longitude: Float, $locationName: String,
                        $sourceType: String, $sourceName: String, $rawText: String) {
  reportSighting(plate: $plate, latitude: $latitude, longitude: $longitude, locationName: $locationName,
                 sourceType: $sourceType, sourceName: $sourceName, rawText: $rawText) {
    found plate id vehicleType brand line color modelYear reason priority notes
  }
}
"""

CREATE_DETECTION = """
mutation CreatePlateDetection($input: CreatePlateDetectionInput!) {
  createPlateDetection(input: $input) { id }
}
"""


class ApiError(Exception):
    pass


class Api:
    def __init__(self, session: Session, timeout_s: float = 10.0):
        self.session = session
        self.timeout_s = timeout_s
        self.http = requests.Session()

    def _run(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.http.post(
                self.session.config.graphql_url,
                json={"query": query, "variables": variables},
                headers={"Authorization": self.session.token()},
                timeout=self.timeout_s,
            )
        except requests.RequestException as error:
            raise ApiError(f"Sin conexión con el servidor: {error}") from error
        if response.status_code >= 400:
            raise ApiError(f"Error del servidor ({response.status_code}): {response.text[:200]}")
        body = response.json()
        if body.get("errors"):
            raise ApiError(body["errors"][0].get("message", "Error GraphQL"))
        return body["data"]

    def report_sighting(self, plate: str, *, camera_name: str, location_name: str,
                        latitude: float | None, longitude: float | None, raw_text: str = "") -> dict[str, Any]:
        data = self._run(REPORT_SIGHTING, {
            "plate": plate,
            "latitude": latitude,
            "longitude": longitude,
            "locationName": location_name,
            "sourceType": "fija",
            "sourceName": camera_name,
            "rawText": raw_text,
        })
        return data["reportSighting"]

    def create_detection(self, plate: str, wanted_plate_id: str | None, *, camera_name: str,
                         location_name: str, latitude: float | None, longitude: float | None) -> str | None:
        payload = {
            "plate": plate,
            "wantedPlateId": wanted_plate_id,
            "status": "alerta",
            "sourceType": "fija",
            "locationName": location_name,
            "latitude": latitude,
            "longitude": longitude,
            "detectedBy": camera_name,
            "detectedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        data = self._run(CREATE_DETECTION, {"input": {k: v for k, v in payload.items() if v is not None}})
        return (data.get("createPlateDetection") or {}).get("id")
