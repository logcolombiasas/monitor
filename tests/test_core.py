import threading
import time

from sia_monitor.config import AppConfig, CameraConfig
from sia_monitor.plates import format_plate, match_format, parse_plate
from sia_monitor.reporter import PlateRead, Reporter
from sia_monitor.tracker import PlateTracker


# --- Placas -----------------------------------------------------------------

def test_parse_formatos_colombianos():
    assert parse_plate("ABC-123") == "ABC123"
    assert parse_plate("abc 12d") == "ABC12D"
    assert parse_plate("XYZ12") == "XYZ12"


def test_corrige_confusiones_del_ocr_por_posicion():
    assert parse_plate("A8C1O3") == "ABC103"
    assert match_format("ABCO1O", "LLLDDD") is None  # dos correcciones en dígitos: se descarta


def test_rechaza_texto_que_no_es_placa():
    assert parse_plate("BOGOTA") is None
    assert parse_plate("") is None
    assert parse_plate("REPUBL") is None


def test_format_plate():
    assert format_plate("ABC123") == "ABC-123"


# --- Confirmación -----------------------------------------------------------

def test_tracker_confirma_con_lecturas_repetidas_y_respeta_cooldown():
    t = PlateTracker(min_hits=2, window_s=3, cooldown_s=600)
    assert t.push(["ABC123"], now=0) == []
    assert t.push(["ABC123"], now=1) == ["ABC123"]
    assert t.push(["ABC123"], now=2) == []  # carro estacionado: no se repite
    assert t.push(["ABC123"], now=700) == []
    assert t.push(["ABC123"], now=701) == ["ABC123"]


def test_tracker_ignora_lecturas_aisladas():
    t = PlateTracker(min_hits=2, window_s=3, cooldown_s=600)
    assert t.push(["XYZ987"], now=0) == []
    assert t.push(["XYZ987"], now=10) == []


# --- Configuración ----------------------------------------------------------

def test_config_guarda_y_carga(tmp_path):
    cfg = AppConfig(cameras=[CameraConfig(name="Entrada", source="rtsp://x/1", location_name="Parqueadero 80",
                                          latitude=4.7, longitude=-74.1)], username="cam@x.com")
    path = tmp_path / "config.json"
    cfg.save(path)
    loaded = AppConfig.load(path)
    assert loaded.username == "cam@x.com"
    assert loaded.cameras[0].location_name == "Parqueadero 80"
    assert loaded.cameras[0].id == cfg.cameras[0].id


# --- Envío al servidor ------------------------------------------------------

class FakeApi:
    def __init__(self, fail_times=0, found=False):
        self.fail_times = fail_times
        self.found = found
        self.reports = []
        self.detections = []

    def report_sighting(self, plate, **kwargs):
        if self.fail_times:
            self.fail_times -= 1
            raise ConnectionError("sin internet")
        self.reports.append((plate, kwargs))
        return {"found": self.found, "plate": plate, "id": "w1" if self.found else None}

    def create_detection(self, plate, wanted_plate_id, **kwargs):
        self.detections.append((plate, wanted_plate_id, kwargs))
        return "d1"


def _wait(predicate, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_reporter_envia_y_crea_deteccion_si_esta_en_listado():
    api = FakeApi(found=True)
    results = []
    reporter = Reporter(api, on_result=lambda read, res: results.append(res))
    reporter.start()
    cam = CameraConfig(name="Cam 1", source="0", location_name="Parqueadero 80", latitude=4.7, longitude=-74.1)
    reporter.submit(PlateRead(plate="ABC123", camera=cam, confidence=0.9))
    assert _wait(lambda: results)
    reporter.stop()
    plate, kwargs = api.reports[0]
    assert plate == "ABC123" and kwargs["location_name"] == "Parqueadero 80" and kwargs["latitude"] == 4.7
    assert api.detections[0][:2] == ("ABC123", "w1")


def test_reporter_reintenta_si_no_hay_internet():
    api = FakeApi(fail_times=2)
    results, statuses = [], []
    reporter = Reporter(api, on_result=lambda read, res: results.append(res),
                        on_status=lambda online, pending: statuses.append(online))
    reporter.start()
    reporter.submit(PlateRead(plate="XYZ987", camera=CameraConfig(name="c", source="0"), confidence=0.9))
    assert _wait(lambda: results, timeout=15)
    reporter.stop()
    assert False in statuses and statuses[-1] is True
    assert api.detections == []
