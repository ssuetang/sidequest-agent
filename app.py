"""Day as Someone: the one entrypoint.

Local:      uv run app.py            then open http://localhost:8000
Cloud Run:  the same command; Cloud Run sets $PORT and we bind 0.0.0.0.

The server itself lives in server/main.py (`app` is re-exported here, so
`uvicorn app:app` works too).
"""

import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()  # local API keys from .env (TICKETMASTER_API_KEY, ...); Cloud Run sets real env vars

from server.main import app  # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    uvicorn.run(app, host=host, port=port)
