import pytest

from app.realtime.gateway import origin_allowed

ALLOWED = ["https://web.example"]
API_HOST = "api.example.app"


@pytest.mark.req("DM-003")
@pytest.mark.parametrize(
    ("origin", "host", "expected"),
    [
        (None, API_HOST, True),  # native client without an Origin
        ("https://web.example", API_HOST, True),  # allow-listed browser app
        ("https://api.example.app", API_HOST, True),  # React Native's default: the API itself
        ("http://API.Example.app", "api.example.app", True),  # TLS ended by the proxy, any case
        ("https://api.example.app:8443", "api.example.app:8443", True),
        ("https://evil.example", API_HOST, False),  # cross-site page
        ("https://api.example.app.evil.example", API_HOST, False),
        ("https://evil.example", None, False),
        ("https://api.example.app:8443", API_HOST, False),  # another port is another origin
        ("null", API_HOST, False),
    ],
)
def test_origin_check(origin: str | None, host: str | None, expected: bool) -> None:
    assert origin_allowed(origin, host, ALLOWED) is expected
