# api/index.py
import os, sys
from fastapi import FastAPI

# Ensure the repo root (where app.py lives) is importable
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

# Import your existing FastAPI app
from app import app as fastapi_app

# Mount it twice so BOTH /random AND /api/random work,
# regardless of how Vercel forwards the path.
app = FastAPI()
app.mount("/", fastapi_app)
