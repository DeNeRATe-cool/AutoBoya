from typer.testing import CliRunner

from autoboya.cli import app


def test_cli_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert "autoboya" in result.output


def test_help_short_alias():
    result = CliRunner().invoke(app, ["-h"])
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_nested_help_short_alias():
    result = CliRunner().invoke(app, ["courses", "auto-preview", "-h"])
    assert result.exit_code == 0
    assert "Usage:" in result.output
