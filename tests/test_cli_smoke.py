from typer.testing import CliRunner

from autoboya.cli import app


def test_cli_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert "autoboya" in result.output
