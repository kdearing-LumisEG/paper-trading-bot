import trading_bot


def test_package_imports() -> None:
    assert trading_bot.__version__ == "0.1.0"
