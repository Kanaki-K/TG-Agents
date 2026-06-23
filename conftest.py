"""Pytest: гарантируем, что корень репозитория в sys.path, чтобы `from core import ...`
работал при запуске `pytest` из любой папки. Сам факт conftest.py в корне делает корень
rootdir'ом; явная вставка — на случай нестандартного режима импорта."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
