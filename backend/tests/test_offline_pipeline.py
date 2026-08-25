import json
import socket
import sys
from pathlib import Path

from run_offline_pipeline import main, run_offline_pipeline


def test_fixed_fixture_builds_review_artifacts_without_network(monkeypatch, capsys):
    def block_network(*_args, **_kwargs):
        raise AssertionError("offline pipeline attempted network access")

    monkeypatch.setattr(socket, "create_connection", block_network)
    monkeypatch.setattr(socket.socket, "connect", block_network)

    preview_path, draft_path = run_offline_pipeline(Path("output/test-offline"))

    assert preview_path.name == "preview.html"
    assert draft_path.name == "publish_draft.json"
    assert "脱敏样本" in preview_path.read_text(encoding="utf-8")
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert draft["title"].startswith("脱敏样本")
    assert draft["carousel_images"] == ["kept/kept_0.svg"]
    assert draft["plan"]["stock"] == 12

    monkeypatch.setattr(sys, "argv", ["run_offline_pipeline.py", "--fixture", "missing.json"])
    assert main() == 1
    assert "[offline] failed: FileNotFoundError" in capsys.readouterr().err
