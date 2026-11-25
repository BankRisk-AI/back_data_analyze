"""Alert profile resolution and labels: default = active profile of module.yaml; labels come from the sha."""
import pytest

from app.core.exceptions import BadRequestError, NotFoundError
from app.modules.eba_rules.application import alert_queries as analysis
from app.modules.eba_rules.application.profiles import profile_labels

V11 = "28a28fa0f89da8435abdb0d6042a69cb2bff421c456926374dd202e0089f7e40"
V10 = "5a1ec1f44d9bfdc55518e3792b593a97e60c97c7405d8c918d7be2525bcc4d5c"   # newest by creation time in prod
V0 = "1296bd8e5a16fcd1d644a77b436ba64b17cfa4f98eb659a67be5213814c8bfad"


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *_args):
        pass

    def fetchall(self):
        return self.rows


def cursor():
    # newest first, as the query orders them: the frozen v1.1 is NOT the newest
    return Cursor([("eu_eba", V10, None), ("eu_eba", V11, None), ("eu_eba", V0, None)])


def test_default_is_the_active_profile_not_the_newest_by_creation_time():
    assert analysis._resolve_profile(cursor(), None) == ("eu_eba", V11)
    assert analysis._resolve_profile(cursor(), "eu_eba") == ("eu_eba", V11)


def test_old_shas_stay_selectable_by_full_sha_and_prefix():
    assert analysis._resolve_profile(cursor(), V10) == ("eu_eba", V10)
    assert analysis._resolve_profile(cursor(), "1296bd8e") == ("eu_eba", V0)


def test_prefix_ambiguity_and_unknown_profile_errors():
    two = Cursor([("eu_eba", "a" * 64, None), ("eu_eba", "a" * 63 + "b", None)])
    with pytest.raises(BadRequestError):
        analysis._resolve_profile(two, "aaaaaaaa")
    with pytest.raises(NotFoundError, match="eu_eba v1.1"):
        analysis._resolve_profile(cursor(), "missing")


def test_missing_active_profile_alerts_is_an_error_not_a_silent_fallback():
    only_old = Cursor([("eu_eba", V10, None)])
    with pytest.raises(NotFoundError, match="available profiles"):
        analysis._resolve_profile(only_old, None)


def test_labels_come_from_the_sha():
    labels = profile_labels()
    assert labels[V11] == {"name": "eu_eba", "version": "1.1", "frozen": True}
    assert labels[V10]["version"] == "1.0" and labels[V0]["version"] == "0"
    assert analysis._label("eu_eba", "f" * 64, labels) == {"name": "eu_eba", "version": None, "frozen": None}
    avail = analysis._available_profiles(cursor())
    assert {p["sha"][:8]: p["version"] for p in avail} == {"5a1ec1f4": "1.0", "28a28fa0": "1.1", "1296bd8e": "0"}
