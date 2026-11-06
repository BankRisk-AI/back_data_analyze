"""ASGI entry point:  uvicorn main:app --reload   (or: make dev)"""
from app.main import app_from_env

app = app_from_env()
