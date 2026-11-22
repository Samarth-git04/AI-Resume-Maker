import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent

load_dotenv(BACKEND_DIR / ".env")

ONLYOFFICE_JWT_SECRET = os.getenv("ONLYOFFICE_JWT_SECRET")
ONLYOFFICE_SERVER_URL = os.getenv("ONLYOFFICE_SERVER_URL")
BACKEND_INTERNAL_URL = os.getenv("BACKEND_INTERNAL_URL")
BACKEND_PUBLIC_URL = os.getenv("BACKEND_PUBLIC_URL")