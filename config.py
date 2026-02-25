import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "instance", "agent.db") + "?check_same_thread=False"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload
    SCHEDULER_API_ENABLED = True
    # Seconds between IMAP reply checks (default: 30 min)
    REPLY_CHECK_INTERVAL = int(os.environ.get("REPLY_CHECK_INTERVAL", 1800))
    # Seconds between daily follow-up checks (default: 24h)
    FOLLOWUP_CHECK_INTERVAL = int(os.environ.get("FOLLOWUP_CHECK_INTERVAL", 86400))
