"""Configuración persistente: cámaras y preferencias (JSON en la carpeta del usuario)."""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import APP_NAME


def data_dir() -> Path:
    """%APPDATA%\\SIA Monitor en Windows, ~/.config/sia-monitor en otros."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
        path = base / APP_NAME
    else:
        path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "sia-monitor"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class CameraConfig:
    name: str
    source: str
    """URL RTSP/HTTP, número de webcam USB ("0", "1"...) o ruta a un archivo de video."""
    location_name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    enabled: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    @property
    def display_location(self) -> str:
        return self.location_name or self.name


@dataclass
class AppConfig:
    cameras: list[CameraConfig] = field(default_factory=list)
    username: str = ""
    amplify_outputs: str = ""
    """Ruta a amplify_outputs.json. Vacío = buscarlo junto al programa o en la carpeta de datos."""
    analyze_fps: float = 4.0
    """Cuadros por segundo analizados por cámara."""
    cooldown_minutes: float = 10.0
    """Tiempo antes de volver a registrar la misma placa en la misma cámara."""
    min_confidence: float = 0.6
    sound: bool = True

    @property
    def path(self) -> Path:
        return data_dir() / "config.json"

    def save(self, path: Path | None = None) -> None:
        target = path or self.path
        target.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        target = path or data_dir() / "config.json"
        if not target.exists():
            return cls()
        raw = json.loads(target.read_text(encoding="utf-8"))
        cameras = [CameraConfig(**c) for c in raw.pop("cameras", [])]
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(cameras=cameras, **known)
