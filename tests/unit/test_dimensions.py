"""Dimension decoding of one edition from a synthetic TR_Metadata workbook."""
import yaml
from openpyxl import Workbook

from app.core.dimensions import build_dimensions


def _metadata(path):
    wb = Workbook()
    country = wb.active
    country.title = "Country"
    for row in (["Code", "Label", "ISO_Code"], [1, "Austria", "at"], [2, "Belgium", "be"]):
        country.append(row)
    nace = wb.create_sheet("NACE_codes")
    for row in (["Code", "Label"], [1, "A Agriculture"], [2, "B Mining"]):
        nace.append(row)
    wb.save(path)


def test_build_dimensions_decodes_country_and_nace(tmp_path):
    edition = tmp_path / "prepared" / "2020A"
    edition.mkdir(parents=True)
    _metadata(edition / "TR_Metadata.xlsx")
    paths = build_dimensions(tmp_path / "prepared", tmp_path / "dimensions")
    assert [p.name for p in paths] == ["2020A.yaml"]
    result = yaml.safe_load(paths[0].read_text())
    assert result["status"] == "decoded"
    assert result["dimensions"]["Country"]["1"]["normalised_key"] == "AT"
    assert result["dimensions"]["NACE_codes"]["2"]["normalised_key"] == "B"


def test_build_dimensions_marks_missing_metadata_undecoded(tmp_path):
    (tmp_path / "prepared" / "2016").mkdir(parents=True)
    paths = build_dimensions(tmp_path / "prepared", tmp_path / "dimensions")
    result = yaml.safe_load(paths[0].read_text())
    assert result["status"] == "undecoded" and result["dimensions"] == {}
