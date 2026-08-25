import json
import shutil
import socket
import sys
from pathlib import Path

from run_offline_pipeline import FIXTURE_PATH, main, run_offline_pipeline


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

    external_fixture_dir = Path("output/external-fixture").resolve()
    shutil.rmtree(external_fixture_dir, ignore_errors=True)
    shutil.copytree(FIXTURE_PATH.parent, external_fixture_dir)
    external_fixture = external_fixture_dir / FIXTURE_PATH.name
    rejected_output = Path("output/test-rejected-fixture")
    shutil.rmtree(rejected_output, ignore_errors=True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_offline_pipeline.py",
            "--output",
            str(rejected_output),
            "--fixture",
            str(external_fixture),
        ],
    )
    assert main() == 1
    assert not rejected_output.exists()
    assert "[offline] failed: unsupported arguments: --fixture" in capsys.readouterr().err
    shutil.rmtree(external_fixture_dir)
