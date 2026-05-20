import json

from autoboya.crypto import BykcCrypto
from autoboya.webvpn import to_webvpn_url


def test_webvpn_host_encryption_matches_known_sso_url():
    url = to_webvpn_url("https://sso.buaa.edu.cn/login")
    assert url == (
        "https://d.buaa.edu.cn/https/"
        "77726476706e69737468656265737421e3e44ed225256951300d8db9d6562d/login"
    )


def test_webvpn_host_encryption_matches_known_bykc_url():
    url = to_webvpn_url("https://bykc.buaa.edu.cn/sscv/cas/login")
    assert url == (
        "https://d.buaa.edu.cn/https/"
        "77726476706e69737468656265737421f2ee4a9f69327d517f468ca88d1b203b/sscv/cas/login"
    )


def test_bykc_crypto_round_trip_response_body():
    crypto = BykcCrypto.fixed_key_for_test("ABCDEFGHJKMNPQRS")
    encrypted = crypto.encrypt_plaintext(json.dumps({"status": "0"}, separators=(",", ":")).encode())
    decrypted = crypto.decrypt_response(encrypted)
    assert decrypted == {"status": "0"}
