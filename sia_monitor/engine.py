"""
Motor de reconocimiento de placas (ALPR) basado en fast-alpr:
  1. Un detector YOLO ubica las placas en el cuadro.
  2. Un modelo de OCR especializado en placas lee el texto de cada una.
Todo corre en el PC (ONNX Runtime), sin enviar video a internet.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

from .plates import parse_plate

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Detection:
    plate: str | None
    """Placa colombiana válida, o None si el texto no corresponde a ningún formato."""
    raw_text: str
    confidence: float
    box: tuple[int, int, int, int]


def _mean_confidence(value: float | list[float], length: int) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    values = list(value)[: max(length, 1)]
    return float(sum(values) / len(values)) if values else 0.0


class PlateEngine:
    """Envuelve fast-alpr. Una sola instancia se comparte entre todas las cámaras."""

    def __init__(self, max_parallel: int | None = None):
        from fast_alpr import ALPR  # import diferido: carga ONNX Runtime

        self._alpr = ALPR(
            detector_model="yolo-v9-t-384-license-plate-end2end",
            ocr_model="cct-xs-v2-global-model",
        )
        # Limita cuántas cámaras analizan a la vez para no saturar la CPU
        workers = max_parallel or max(1, (os.cpu_count() or 2) // 2)
        self._slots = threading.Semaphore(workers)

    def detect(self, frame: np.ndarray) -> list[Detection]:
        with self._slots:
            results: list[Any] = self._alpr.predict(frame)
        detections: list[Detection] = []
        for result in results:
            box = result.detection.bounding_box
            ocr = result.ocr
            raw = (ocr.text if ocr else "") or ""
            confidence = _mean_confidence(ocr.confidence, len(raw)) if ocr else 0.0
            detections.append(Detection(
                plate=parse_plate(raw),
                raw_text=raw,
                confidence=confidence,
                box=(int(box.x1), int(box.y1), int(box.x2), int(box.y2)),
            ))
        return detections
