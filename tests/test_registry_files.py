from pathlib import Path
import yaml

REG = Path(__file__).resolve().parents[1] / "core" / "registry"
SEEDSPEC = ("pnr", "pnr_id", "passenger", "route", "ticket",
            "status", "system_code", "amount", "currency", "flags")


def test_feed_files_exist():
    assert (REG / "feeds" / "fd.yaml").exists()
    assert (REG / "feeds" / "soc.yaml").exists()


def test_fd_columns_cover_seedspec():
    d = yaml.safe_load((REG / "feeds" / "fd.yaml").read_text(encoding="utf-8"))
    for field in SEEDSPEC:
        assert field in d["columns"], f"fd.yaml columns missing SeedSpec field '{field}'"


def test_env_otp_strategies():
    crt = yaml.safe_load((REG / "envs" / "crt.yaml").read_text(encoding="utf-8"))
    intd = yaml.safe_load((REG / "envs" / "int.yaml").read_text(encoding="utf-8"))
    # OTP is uniform across envs: every env fetches the REAL code from the mailinator inbox
    # (INT accepts any 6-digit, so the real fetched code works there too — no special "fixed" path).
    assert crt["otp"]["strategy"] == "mailinator"
    assert intd["otp"]["strategy"] == "mailinator"


def test_env_has_no_inline_token():
    crt_text = (REG / "envs" / "crt.yaml").read_text(encoding="utf-8")
    # only a secret NAME may appear, never a raw token value
    assert "token_secret" in crt_text
    assert "225847" not in crt_text  # no real Mailinator token committed
