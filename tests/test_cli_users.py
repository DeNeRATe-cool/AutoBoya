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


def test_user_add_records_campus(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOBOYA_HOME", str(tmp_path / ".autoboya"))
    monkeypatch.setattr("autoboya.cli.try_store_keyring_password", lambda username, password: True)
    runner = CliRunner()

    result = runner.invoke(app, ["user", "add", "23370001", "--campus", "杭州", "--password-stdin"], input="secret\n")
    listed = runner.invoke(app, ["user", "list"])

    assert result.exit_code == 0
    assert listed.exit_code == 0
    assert "campus=杭州" in listed.output
