from typer.testing import CliRunner

from autoboya.cli import app


def test_manual_commands_show_help_without_network():
    runner = CliRunner()
    for command in [
        ["drop", "--help"],
        ["sign", "--help"],
        ["signout", "--help"],
        ["run-once", "--help"],
    ]:
        result = runner.invoke(app, command)
        assert result.exit_code == 0
