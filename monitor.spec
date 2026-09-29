# -*- mode: python ; coding: utf-8 -*-
# Empaquetado para Windows:  pyinstaller monitor.spec
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [("assets", "assets")]
hiddenimports = []
for package in ("fast_alpr", "fast_plate_ocr", "open_image_models"):
    datas += collect_data_files(package)
    hiddenimports += collect_submodules(package)
datas += collect_data_files("onnxruntime")

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "setuptools", "pkg_resources",
               # partes de entrenamiento de fast-plate-ocr que no se usan
               "keras", "tensorflow", "torch", "jax"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LogcolombiaMonitor",
    icon="assets/icon.ico",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="LogcolombiaMonitor")
