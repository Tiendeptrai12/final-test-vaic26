"""Vercel serverless entry (ASGI) — standalone API for the AI Product Advisor.

Separate from backend.py on purpose: backend.py is the on-prem uvicorn server;
this file is the cloud (Vercel) adapter. The frontend now ships in the SAME Vercel
deploy (static UI served via vercel.json rewrites, API here at /api/*), so the app is
one live URL. CORS stays wildcard: harmless same-origin, and keeps a standalone
frontend deploy working too.

Runtime path (live) = mock advisor in antigravity/core.py, so NO catalog data is
required or bundled (NDA-safe). FPT_API_KEY comes from a Vercel Environment
Variable, never from the repo.
"""
import os
import sys

# repo root on sys.path so `antigravity` imports resolve inside the function bundle
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from antigravity.views import router  # noqa: E402

app = FastAPI(title="Điện Máy Xanh - AI Product Advisor (Vercel API)")

# Cross-origin: the frontend runs on a different Vercel domain. No cookies/credentials
# are used, so wildcard origins are safe here (credentials must stay False with "*").
# Lock this to the frontend's domain(s) once the URL is stable.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
