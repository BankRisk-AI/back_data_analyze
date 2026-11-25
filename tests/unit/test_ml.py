from datetime import date

from app.modules.eba_ml.application.dataset import folds


def test_temporal_folds_keep_embargo():
    rows = [{"period": date(year, 6, 30), "bank_id": 1} for year in range(2014, 2025)]
    for train, test in folds(rows):
        assert train.size and test.size
        assert max(rows[i]["period"].year for i in train) < min(
            rows[i]["period"].year for i in test) - 1
