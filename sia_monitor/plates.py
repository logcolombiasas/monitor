"""
Normalización y validación de placas colombianas.

Formatos:
  - Carro / camioneta / camión:  ABC123  (LLLDDD)
  - Moto actual:                 ABC12D  (LLLDDL)
  - Moto antigua:                ABC12   (LLLDD)

El OCR a veces confunde caracteres parecidos (O/0, I/1, B/8, S/5...). Como el
formato indica si en cada posición va letra o número, se corrigen según la
posición, con un máximo de correcciones para no inventar placas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

FORMATS: list[str] = ["LLLDDD", "LLLDDL", "LLLDD"]

TO_LETTER = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "7": "T", "8": "B"}
TO_DIGIT = {
    "O": "0", "Q": "0", "D": "0", "U": "0", "I": "1", "L": "1", "T": "1", "J": "1",
    "Z": "2", "S": "5", "G": "6", "B": "8", "A": "4",
}

MAX_CORRECTIONS = 2
# En posiciones numéricas se corrige como máximo 1 carácter ("REPUBL" no debe ser "REP08L")
MAX_DIGIT_CORRECTIONS = 1


@dataclass(frozen=True)
class PlateMatch:
    plate: str
    corrections: int


def normalize(text: str | None) -> str:
    """Mayúsculas y solo letras/números: 'abc-123' -> 'ABC123'."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def match_format(token: str, pattern: str) -> PlateMatch | None:
    """Ajusta `token` al patrón (L = letra, D = dígito) corrigiendo confusiones del OCR."""
    if len(token) != len(pattern):
        return None
    out: list[str] = []
    corrections = 0
    digit_corrections = 0
    for char, slot in zip(token, pattern):
        if slot == "L":
            if char.isalpha():
                out.append(char)
            elif char in TO_LETTER:
                out.append(TO_LETTER[char])
                corrections += 1
            else:
                return None
        else:
            if char.isdigit():
                out.append(char)
            elif char in TO_DIGIT:
                out.append(TO_DIGIT[char])
                corrections += 1
                digit_corrections += 1
            else:
                return None
        if corrections > MAX_CORRECTIONS or digit_corrections > MAX_DIGIT_CORRECTIONS:
            return None
    return PlateMatch("".join(out), corrections)


def parse_plate(text: str | None) -> str | None:
    """
    Convierte el texto leído por el OCR en una placa colombiana válida,
    o None si no corresponde a ningún formato.
    """
    token = normalize(text)
    best: PlateMatch | None = None
    for pattern in FORMATS:
        match = match_format(token, pattern)
        if match and (best is None or match.corrections < best.corrections):
            best = match
    return best.plate if best else None


def format_plate(plate: str) -> str:
    """ABC123 -> ABC-123"""
    return f"{plate[:3]}-{plate[3:]}" if len(plate) >= 6 else plate
