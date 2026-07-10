"""
WSGI entry point for PythonAnywhere (and other WSGI hosts).

In PythonAnywhere Web tab, set:
  Source code: /home/<username>/WordToExcel
  WSGI file:   /home/<username>/WordToExcel/wsgi.py
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv

load_dotenv(BASE_DIR / ".env", override=True)

from index import app as application
