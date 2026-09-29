"""
Confirmación de lecturas por cámara.

Una placa se "confirma" cuando se lee al menos `min_hits` veces dentro de
`window_s`. Después queda en espera `cooldown_s` para que un vehículo parado
frente a la cámara no se registre en cada cuadro.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class PlateTracker:
    min_hits: int = 2
    window_s: float = 3.0
    cooldown_s: float = 600.0
    _sightings: dict[str, list[float]] = field(default_factory=dict)
    _cooldown_until: dict[str, float] = field(default_factory=dict)

    def push(self, plates: list[str], now: float | None = None) -> list[str]:
        """Registra las placas leídas en un cuadro y devuelve las recién confirmadas."""
        now = time.monotonic() if now is None else now
        confirmed: list[str] = []
        for plate in dict.fromkeys(plates):
            if self._cooldown_until.get(plate, 0) > now:
                continue
            hits = [t for t in self._sightings.get(plate, []) if now - t <= self.window_s]
            hits.append(now)
            if len(hits) >= self.min_hits:
                self._sightings.pop(plate, None)
                self._cooldown_until[plate] = now + self.cooldown_s
                confirmed.append(plate)
            else:
                self._sightings[plate] = hits
        self._cleanup(now)
        return confirmed

    def release(self, plate: str) -> None:
        """Permite volver a evaluar una placa (ej. si el envío al servidor falló)."""
        self._cooldown_until.pop(plate, None)

    def _cleanup(self, now: float) -> None:
        if len(self._sightings) < 200 and len(self._cooldown_until) < 2000:
            return
        self._sightings = {
            p: hits for p, hits in self._sightings.items() if any(now - t <= self.window_s for t in hits)
        }
        self._cooldown_until = {p: t for p, t in self._cooldown_until.items() if t > now}
