"""Content-addressed model artifact storage."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from app.core.config import get_storage_dir


class ArtifactStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or get_storage_dir()) / "models"

    def _directory(self, sha256: str) -> Path:
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ValueError("invalid artifact hash")
        return self.root / sha256

    def put(self, payload: bytes, model_card: dict) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        destination = self._directory(digest)
        if destination.exists():
            return digest
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".model-", dir=self.root))
        try:
            (temporary / "model.bin").write_bytes(payload)
            (temporary / "model_card.json").write_text(
                json.dumps(model_card, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        return digest

    def load(self, sha256: str) -> bytes:
        payload = (self._directory(sha256) / "model.bin").read_bytes()
        if hashlib.sha256(payload).hexdigest() != sha256:
            raise ValueError("model artifact sha256 verification failed")
        return payload

    def card(self, sha256: str) -> dict:
        self.load(sha256)
        return json.loads((self._directory(sha256) / "model_card.json").read_text(
            encoding="utf-8"))

    def load_model(self, sha256: str, format_name: str):
        payload = self.load(sha256)
        if format_name == "xgboost_json":
            import tempfile
            from xgboost import XGBClassifier
            with tempfile.NamedTemporaryFile(suffix=".json") as handle:
                handle.write(payload)
                handle.flush()
                model = XGBClassifier()
                model.load_model(handle.name)
                return model
        if format_name == "joblib":
            import io
            import joblib
            return joblib.load(io.BytesIO(payload))
        raise ValueError(f"unsupported model artifact format: {format_name}")

    def remove(self, sha256: str) -> None:
        shutil.rmtree(self._directory(sha256))
