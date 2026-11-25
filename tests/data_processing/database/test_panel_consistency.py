"""Rules and ML start from the same panel: the indicator values they use are equal."""
import pytest
from ml_synthetic import clear_panel, seed_panel

from app.core.panel_reader import load_panel
from app.modules.eba_ml.application.dataset import build_dataset
from app.modules.eba_ml.domain.constants import FEATURES
from app.modules.eba_rules.public import evaluate_panel


@pytest.fixture()
def seeded(db):
    seed_panel(db.cur)
    yield db
    clear_panel(db.cur)


def test_the_values_entering_rules_equal_the_values_entering_the_ml_dataset(seeded):
    panel = {(r["bank_id"], r["period"]): r for r in load_panel(seeded.cur).rows}
    dataset = build_dataset(seeded.conn, "semiannual", True)
    assert dataset["rows"], "synthetic panel must produce ML rows"
    for row in dataset["rows"]:                                   # ML dataset == load_panel (indicator by indicator)
        source = panel[(row["bank_id"], row["period"])]
        assert all(row[f] == source[f] for f in FEATURES)
    alerts = evaluate_panel(seeded.conn, "eu_eba", persist=False)  # rules input == load_panel as well
    checked = 0
    for alert in alerts:
        rule = next(r for r in alert["rule_results"]["rules"] if r["rule_id"] == "cet1_regulatory_min")
        bank_period = next(k for k, v in panel.items()
                           if v["bank_id"] == alert["bank_id"] and v["dataset_version"] == alert["dataset_version"])
        assert rule["input_value"] == panel[bank_period]["cet1_ratio"]
        checked += 1
    assert checked == len(panel)
    assert {r["bank_id"] for r in dataset["rows"]} <= {k[0] for k in panel}
