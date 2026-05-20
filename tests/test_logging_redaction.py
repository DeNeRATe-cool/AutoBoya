from autoboya.logging import redact


def test_redact_sensitive_values():
    text = "Authtoken abc123 password=secret CASTGC=TGT-1 user [22312345]"
    redacted = redact(text)

    assert "secret" not in redacted
    assert "TGT-1" not in redacted
    assert "22312345" not in redacted
