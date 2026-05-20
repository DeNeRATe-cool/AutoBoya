from typer.testing import CliRunner

from autoboya.cli import app


def test_init_and_empty_user_list(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOBOYA_HOME", str(tmp_path / ".autoboya"))
    runner = CliRunner()

    init_result = runner.invoke(app, ["init"])
    assert init_result.exit_code == 0

    listed = runner.invoke(app, ["user", "list"])
    assert listed.exit_code == 0
    assert "No users" in listed.output
