"""Serverless entry point (Vercel Python runtime, ADR-0019).

Vercel imports this module and serves the ASGI ``app``. Configuration comes from environment
variables, validated at import time by the same production guards as every other deployment.
Long-running process roles (realtime gateway, workers) are not deployed here.
"""

from app.main import create_app

app = create_app()
