from core.cli import main


def test_list_returns_zero(capsys):
    rc = main(["list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "fd" in out and "crt" in out and "bravo" in out


def test_validate_clean_returns_zero(capsys):
    rc = main(["validate"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK" in out or "clean" in out.lower()


def test_unknown_command_returns_nonzero():
    assert main(["frobnicate"]) != 0
