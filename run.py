"""Punto de entrada para PyInstaller y para ejecutar desde el código fuente."""
import sys

from logcolombia_monitor.app import main

if __name__ == "__main__":
    sys.exit(main())
