from pathlib import Path

import yaml

from app.core.dimensions import build_dimensions


def test_build_dimensions_decodes_country_and_nace(tmp_path):
    source = tmp_path / "prepared"
    edition = source / "2020A"
    edition.mkdir(parents=True)
    (edition / "TR_Metadata.xlsx").write_bytes(
        Path("eba_prepared/2020A/TR_Metadata.xlsx").read_bytes()
    )

    output = tmp_path / "dimensions"
    paths = build_dimensions(source, output)

    assert [path.name for path in paths] == ["2020A.yaml"]
    result = yaml.safe_load(paths[0].read_text())
    assert result["status"] == "decoded"
    assert result["dimensions"]["Country"]["1"]["normalised_key"] == "AT"
    assert result["dimensions"]["NACE_codes"]["1"]["normalised_key"] == "A"


def test_build_dimensions_marks_missing_metadata_undecoded(tmp_path):
    source = tmp_path / "prepared"
    (source / "2016").mkdir(parents=True)

    paths = build_dimensions(source, tmp_path / "dimensions")

    result = yaml.safe_load(paths[0].read_text())
    assert result["status"] == "undecoded"
    assert result["dimensions"] == {}
