"""Pure profile-edit rules (BL-1.04) and UI locale negotiation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.i18n import negotiate_ui_locale
from app.modules.profiles.domain import (
    clean_display_name,
    clean_optional_text,
    clean_tags,
    dedupe,
    is_reserved_handle,
    next_handle_change_at,
)


@pytest.mark.security
@pytest.mark.parametrize(
    ("handle", "reserved"),
    [
        ("admin", True),
        ("a.d.m.i.n", True),
        ("support_", True),
        ("travelbuddy.help", True),
        ("the_travel_buddy", True),
        ("ana.souza", False),
        ("administrador", False),
    ],
)
def test_reserved_handles(handle: str, reserved: bool) -> None:
    assert is_reserved_handle(handle) is reserved


@pytest.mark.req("PROF-003")
def test_handle_change_window() -> None:
    assert next_handle_change_at(None) is None
    changed = datetime(2026, 11, 1, tzinfo=UTC)
    assert next_handle_change_at(changed) == changed + timedelta(days=30)


@pytest.mark.security
def test_display_name_strips_invisible_and_bidi_characters() -> None:
    assert clean_display_name(" Ana‮  Souza​ ") == "Ana Souza"
    with pytest.raises(ValueError, match="visible"):
        clean_display_name("​ ⁦")
    with pytest.raises(ValueError, match="at most"):
        clean_display_name("x" * 51)


def test_optional_text_normalizes_newlines_and_empties() -> None:
    assert clean_optional_text(None, max_length=10, multiline=True) is None
    assert clean_optional_text("   ", max_length=10, multiline=False) is None
    assert clean_optional_text("a\r\n\r\n\r\nb  ", max_length=10, multiline=True) == "a\n\nb"
    assert clean_optional_text(" a \n b ", max_length=10, multiline=False) == "a b"
    with pytest.raises(ValueError, match="at most"):
        clean_optional_text("x" * 11, max_length=10, multiline=False)


def test_tags_are_deduplicated_case_insensitively() -> None:
    assert clean_tags(["Food", " food ", "", "Art  Deco"], max_length=40) == ["Food", "Art Deco"]
    with pytest.raises(ValueError, match="at most"):
        clean_tags(["x" * 41], max_length=40)
    assert dedupe(["pt-BR", "en", "PT-br"]) == ["pt-BR", "en"]


@pytest.mark.req("I18N-002")
@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("pt-BR", "pt-BR"),
        ("pt-br", "pt-BR"),
        ("pt-PT", "pt-BR"),
        ("de-AT", "de"),
        ("es-419", "es"),
        ("ja", "en"),
        (None, "en"),
    ],
)
def test_ui_locale_negotiation(tag: str | None, expected: str) -> None:
    assert negotiate_ui_locale(tag) == expected
