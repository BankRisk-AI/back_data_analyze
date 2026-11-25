from app.core.dictionary import _data_items


def test_data_only_items_count_non_aggregate_rows(tmp_path):
    root = tmp_path / "prepared"
    edition = root / "2016"
    edition.mkdir(parents=True)
    (edition / "tr_oth_2016.csv").write_text(
        "Item,Label,LEI_Code,NSA\n"
        "160001,Metric,XXXXXXXXXXXXXXXXXXXX,OT\n"
        "160001,Metric,LEI0000000000000001,DE\n"
        "160002,Other,LEI0000000000000002,FR\n",
        encoding="cp1252",
    )

    items, _ = _data_items(root)

    assert items[("2016", "oth", "160001")] == ("Metric", 1)
    assert items[("2016", "oth", "160002")] == ("Other", 1)
