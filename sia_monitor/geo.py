"""Lectura de coordenadas escritas o pegadas por el usuario."""

from __future__ import annotations

import re

_NUMBER = r"[-+]?\d{1,3}(?:\.\d+)?"


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """
    Acepta los formatos más comunes al copiar una ubicación:
      - "4.6860, -74.0560"  (clic derecho en Google Maps → copiar coordenadas)
      - "4.6860 -74.0560" o "4.6860; -74.0560"
      - Enlace de Google Maps con "@4.6860,-74.0560,17z" o "?q=4.6860,-74.0560"
    Devuelve (latitud, longitud) o None si no es válido.
    """
    value = (text or "").strip()
    if not value:
        return None
    match = re.search(rf"@({_NUMBER}),({_NUMBER})", value) or re.search(rf"[?&]q=({_NUMBER}),({_NUMBER})", value)
    if not match:
        match = re.fullmatch(rf"\s*({_NUMBER})\s*[,; ]\s*({_NUMBER})\s*", value)
    if not match:
        return None
    lat, lng = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        return None
    return lat, lng


def format_coordinates(lat: float | None, lng: float | None) -> str:
    return "" if lat is None or lng is None else f"{lat:.6f}, {lng:.6f}"
