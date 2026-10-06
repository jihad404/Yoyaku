"""Logging für den Bot: Konsole (landet bei systemd im Journal) und eine
rotierende Datei logs/yoyaku.log.

Datenschutz: Es werden nur interne Nutzer-IDs geloggt, keine Namen oder Geburtsdaten.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_FILE = "yoyaku.log"
MAX_BYTES = 1_000_000   # 1 MB pro Datei
BACKUP_COUNT = 5        # yoyaku.log + 5 ältere = max. 6 MB

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

# Bibliotheken, die sonst jede Anfrage loggen (httpx sogar mit Bot-Token in der URL)
QUIET_LOGGERS = ("httpx", "httpcore", "apscheduler", "telegram.ext.Application")


def setup_logging(log_dir: str = LOG_DIR, level: int = logging.INFO) -> None:
    os.makedirs(log_dir, exist_ok=True)
    formatter = logging.Formatter(FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = RotatingFileHandler(os.path.join(log_dir, LOG_FILE), maxBytes=MAX_BYTES,
                                       backupCount=BACKUP_COUNT, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
