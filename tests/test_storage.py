from pathlib import Path

from autoboya.storage import AutoBoyaStore


def test_store_initializes_expected_directories(tmp_path: Path):
    store = AutoBoyaStore(root=tmp_path / ".autoboya")
    store.init()

    assert (tmp_path / ".autoboya" / "cache").is_dir()
    assert (tmp_path / ".autoboya" / "logs").is_dir()
    assert (tmp_path / ".autoboya" / "run").is_dir()
    assert (tmp_path / ".autoboya" / "captcha").is_dir()
    assert (tmp_path / ".autoboya" / "users.json").exists()
    assert store.load_users() == []


def test_atomic_json_round_trip(tmp_path: Path):
    store = AutoBoyaStore(root=tmp_path / ".autoboya")
    store.init()
    store.save_json("settings.json", {"auto_select_mode": "autonomous_sign_only"})

    assert store.load_json("settings.json") == {"auto_select_mode": "autonomous_sign_only"}
