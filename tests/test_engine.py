"""
Pruebas con el motor ALPR real (descarga los modelos la primera vez).
Se omiten si los modelos no se pueden cargar (sin internet).
"""

import time

import cv2
import numpy as np
import pytest

from logcolombia_monitor.camera import CameraWorker
from logcolombia_monitor.config import CameraConfig


def synthetic_frame(text: str = "ABC 123") -> np.ndarray:
    img = np.full((480, 800, 3), 90, np.uint8)
    cv2.rectangle(img, (250, 200), (550, 300), (0, 212, 255), -1)  # fondo amarillo
    cv2.rectangle(img, (250, 200), (550, 300), (0, 0, 0), 4)
    cv2.putText(img, text, (272, 272), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 6)
    return img


@pytest.fixture(scope="module")
def engine():
    try:
        from logcolombia_monitor.engine import PlateEngine
        return PlateEngine()
    except Exception as error:  # sin internet para descargar modelos
        pytest.skip(f"Motor ALPR no disponible: {error}")


def test_detecta_placa_en_cuadro(engine):
    detections = engine.detect(synthetic_frame())
    assert any(d.plate == "ABC123" and d.confidence > 0.6 for d in detections)


def test_camara_confirma_y_entrega_lectura(engine):
    reads, frames = [], []
    worker = CameraWorker(
        CameraConfig(name="Entrada", source="0", location_name="Parqueadero 80"),
        engine,
        on_read=reads.append,
        on_frame=frames.append,
        on_state=lambda *a: None,
    )
    frame = synthetic_frame()
    assert worker.process(frame, now=0) == []
    assert worker.process(frame, now=1) == ["ABC123"]
    assert worker.process(frame, now=2) == []  # en espera (cooldown)
    assert len(reads) == 1 and reads[0].plate == "ABC123"
    assert reads[0].snapshot is not None and reads[0].snapshot.size > 0
    assert len(frames) == 3


def test_camara_lee_archivo_de_video(engine, tmp_path):
    """Flujo completo con un archivo de video como fuente (igual que un stream RTSP)."""
    path = str(tmp_path / "prueba.avi")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 10, (800, 480))
    for _ in range(30):
        writer.write(synthetic_frame("XYZ 987"))
    writer.release()

    reads, states = [], []
    worker = CameraWorker(
        CameraConfig(name="Video", source=path),
        engine,
        on_read=reads.append,
        on_frame=lambda f: None,
        on_state=lambda cid, state, msg: states.append(state),
        analyze_fps=10,
    )
    worker.start()
    end = time.time() + 20
    while not reads and time.time() < end:
        time.sleep(0.1)
    worker.stop()
    worker.join()
    assert reads and reads[0].plate == "XYZ987"
    assert "En vivo" in [s.value for s in states]
