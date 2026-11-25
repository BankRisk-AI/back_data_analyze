"""A modified frozen profile is a problem+json error, not a 500."""
import shutil

from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.eba_rules.application import profiles


def test_a_modified_frozen_profile_gives_a_409_problem_with_a_clear_message(db, tmp_path, monkeypatch):
    target = tmp_path / "config"
    shutil.copytree(profiles.CONFIG_DIR, target)
    monkeypatch.setattr(profiles, "CONFIG_DIR", target)
    path = target / "profiles" / "eu_eba_v1.1.yaml"
    path.write_text(path.read_text() + "\n# edited\n")
    client = TestClient(create_app(schema=db.schema), raise_server_exceptions=False)
    response = client.get("/api/public/alerts", params={"period": "202006"})
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "profile-integrity"
    assert "frozen profile eu_eba was modified: sha mismatch" in body["detail"]
