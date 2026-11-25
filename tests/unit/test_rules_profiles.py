"""eba_rules profile loader: strict schema, frozen profiles verified by sha256, single source of levels."""
import shutil

import pytest

from app.modules.eba_rules.application import profiles
from app.modules.eba_rules.domain.profile_schema import validate_profile
from app.modules.eba_rules.public import (
    ProfileIntegrityError, choose_r1_margin, compliant, load_profile, r0_alert, r1_alert,
    r1_margin_grid_pp, regulatory_levels)

EU_SHA = "28a28fa0f89da8435abdb0d6042a69cb2bff421c456926374dd202e0089f7e40"


def test_frozen_eu_profile_loads_with_its_recorded_sha():
    profile, sha = load_profile("eu_eba")
    assert sha == EU_SHA and profile["version"] == "1.1" and profile["frozen"] is True


@pytest.fixture()
def config_copy(tmp_path, monkeypatch):
    target = tmp_path / "config"
    shutil.copytree(profiles.CONFIG_DIR, target)
    monkeypatch.setattr(profiles, "CONFIG_DIR", target)
    return target


def test_an_edited_frozen_profile_fails_loudly(config_copy):
    path = config_copy / "profiles" / "eu_eba_v1.1.yaml"
    path.write_text(path.read_text().replace("threshold: 0.045", "threshold: 0.046", 1) + "\n# edited\n")
    with pytest.raises(ProfileIntegrityError, match="frozen profile eu_eba"):
        load_profile("eu_eba")


def test_an_adjustable_profile_is_not_sha_checked(config_copy):
    path = config_copy / "profiles" / "bnm.yaml"
    path.write_text(path.read_text() + "\n# adjustable\n")
    assert load_profile("bnm")[0]["profile"] == "bnm"


def test_unknown_profile_and_unknown_keys_are_errors():
    with pytest.raises(KeyError):
        load_profile("nope")
    profile, _ = load_profile("eu_eba")
    with pytest.raises(ValueError, match="unknown keys"):
        validate_profile({**profile, "surprise": 1})
    bad_rule = {**profile["rules"][0], "colour": "red"}
    with pytest.raises(ValueError, match="unknown keys"):
        validate_profile({**profile, "rules": [bad_rule, *profile["rules"][1:]]})


def test_regulatory_levels_are_the_single_source():
    assert regulatory_levels() == {"cet1": 0.07, "tier1": 0.085, "total_capital": 0.105}
    assert r1_margin_grid_pp()[0] == 0.0 and r1_margin_grid_pp()[-1] == 20.0
    with pytest.raises(ValueError, match="no regulatory levels"):
        regulatory_levels("bnm")


def test_r0_r1_and_compliance_on_known_rows():
    levels = regulatory_levels()
    ok = {"cet1_ratio": 0.10, "tier1_ratio": 0.11, "total_capital_ratio": 0.13}
    low = {**ok, "cet1_ratio": 0.065}
    assert compliant(ok, levels) and not r0_alert(ok, levels)
    assert r0_alert(low, levels) and not compliant(low, levels)
    assert r1_alert(ok, levels, 0.04) and not r1_alert(ok, levels, 0.02)
    assert not compliant({**ok, "tier1_ratio": None}, levels) and not r0_alert({**ok, "tier1_ratio": None}, levels)
    import numpy as np
    margin, f2 = choose_r1_margin([ok, low], np.array([0, 1]), levels, [0.0, 1.0])
    assert margin == 0.0 and f2 == 1.0
