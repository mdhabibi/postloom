from datetime import UTC, datetime

import pytest

from postloom.domain.errors import InvalidProfileUrlError
from postloom.domain.people import Person, ProfileUrl

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2026, 6, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.linkedin.com/in/jane-example/",
        "http://de.linkedin.com/in/Jane-Example?trk=public_profile",
        "linkedin.com/in/jane-example",
        "  https://linkedin.com/in/jane-example/details/experience/  ",
    ],
)
def test_profile_url_spellings_normalize_to_one_identity(raw: str) -> None:
    profile = ProfileUrl.parse(raw)
    assert profile.slug == "jane-example"
    assert profile.url == "https://www.linkedin.com/in/jane-example"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "https://example.com/in/jane",
        "https://www.linkedin.com/company/acme",
        "https://www.linkedin.com/in/",
        "https://evil-linkedin.com/in/jane-example",
    ],
)
def test_non_profile_urls_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidProfileUrlError):
        ProfileUrl.parse(raw)


def test_person_id_uses_profile_slug_when_known() -> None:
    person = Person("Jane Example", ProfileUrl.parse("linkedin.com/in/jane-example"))
    assert person.id == "person:jane-example"
    assert not person.is_provisional


def test_person_without_profile_gets_a_flagged_provisional_id() -> None:
    person = Person("Jane Example")
    assert person.id == "person:~jane-example"
    assert person.is_provisional


def test_headline_changes_are_superseded_not_deleted() -> None:
    person = Person("Jane Example").observe("Engineer at Acme", T0).observe("Lead at Beta", T1)
    assert person.headline == "Lead at Beta"
    assert [o.headline for o in person.observations] == ["Engineer at Acme", "Lead at Beta"]
    assert person.observations[0].superseded_at == T1
    assert person.observations[1].is_current


def test_observing_the_same_headline_is_a_no_op() -> None:
    person = Person("Jane Example").observe("Engineer at Acme", T0)
    assert person.observe("Engineer at Acme", T1) is person
    assert person.observe("   ", T1) is person


def test_a_profile_name_can_never_contain_a_path() -> None:
    from postloom.domain.errors import InvalidProfileUrlError

    for bad in ("../../escaped", "a/b", "..", "x"):
        with pytest.raises(InvalidProfileUrlError):
            ProfileUrl(bad)
    assert ProfileUrl("jane-example-42").slug == "jane-example-42"
