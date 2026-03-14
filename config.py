import os
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")

# Call graph settings
CALL_GRAPH_MAX_DEPTH = int(os.getenv("CALL_GRAPH_MAX_DEPTH", "5"))
CALL_GRAPH_TIMEOUT = int(os.getenv("CALL_GRAPH_TIMEOUT", "10"))

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./perf_regressor.db")

# Dashboard
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")