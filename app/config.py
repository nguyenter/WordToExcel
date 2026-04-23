import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "word-to-excel-secret-key")
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "8"))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024

