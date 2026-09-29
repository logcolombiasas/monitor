"""Punto de entrada para PyInstaller y para ejecutar desde el código fuente."""
import sys

from sia_monitor.app import main

if __name__ == "__main__":
    sys.exit(main())
