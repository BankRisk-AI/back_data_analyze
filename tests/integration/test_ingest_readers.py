"""Ingest building blocks that need no database: file names, headers, encoding detection, metadata reader."""
import os, stat, pytest
from openpyxl import Workbook
from app.modules.eba_ingest.domain.services.file_detector import classify_name, normalise_header, missing_required
from app.modules.eba_ingest.infrastructure.storage.storage import store
from app.modules.eba_ingest.application.load_service import _metadata
from app.modules.eba_ingest.infrastructure.readers.readers import xlsx_bank_list_sheet

def test_names_and_headers():
    assert [classify_name(n) for n in ["tr_oth_2.csv", "TR_CRE.xlsx", "tr_mrk.csv", "tr_sov_x.csv", "SDD_2.xlsx", "TR_Metadata_2.xlsx", "notes.txt"]] == ["tr_oth", "tr_cre", "tr_mrk", "tr_sov", "SDD", "TR_Metadata", None]
    assert normalise_header(["LEI_Code", " Period ", "Fin end year"]) == ["lei_code", "period", "fin_end_year"]
    assert missing_required(["lei_code", "period"]) == ["nsa", "item", "amount"]
    with pytest.raises(ValueError): normalise_header(["a", "A"])

def test_encoding_detection_and_immutable_storage(tmp_path):
    utf8 = tmp_path / "a.csv"; utf8.write_bytes("x,y\n\u00e9,1\n".encode("utf-8")); cp = tmp_path / "b.csv"; cp.write_bytes(b"x,y\n\x96,1\n")
    s1 = store(str(utf8), str(tmp_path / "st"), 10**6, True); s2 = store(str(cp), str(tmp_path / "st"), 10**6, True)
    assert s1[3] == "utf-8" and s2[3] == "cp1252"
    assert len(s1[0]) == 64 and os.path.exists(s1[2]) and not (os.stat(s1[2]).st_mode & stat.S_IWUSR)   # read-only
    again = store(str(utf8), str(tmp_path / "st"), 10**6, True); assert again[0] == s1[0] and again[4] is False   # same content: stored once

@pytest.mark.parametrize("sheet", ["Bank list", "Banks list", "List of Institutions", "List of Financial Institutions"])
def test_metadata_reader_finds_bank_list_sheet_and_previous_leis(tmp_path, sheet):
    path = tmp_path / f"{sheet.replace(' ', '_')}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(["title row"])
    ws.append(["LEI_Code", "Name", "Country", "Finrep", "LEI_Code_TR16", "LEI_Code_used_for_2014_stress_test"])
    ws.append(["AAAAAAAAAAAAAAAAAAAA", "Bank", "DE", "Yes", "BBBBBBBBBBBBBBBBBBBB", "CCCCCCCCCCCCCCCCCCCC"])
    wb.save(path)
    assert xlsx_bank_list_sheet(str(path)) == sheet
    assert _metadata(str(path)) == [(
        "AAAAAAAAAAAAAAAAAAAA", "Bank", "DE", True,
        ["BBBBBBBBBBBBBBBBBBBB", "CCCCCCCCCCCCCCCCCCCC"],
    )]

def test_metadata_reader_accepts_2015_bank_name(tmp_path):
    path = tmp_path / "TR_Metadata.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Institutions"
    ws.append(["title row"])
    ws.append(["LEI_Code", "Bank_Name", "Country_Code"])
    ws.append(["AAAAAAAAAAAAAAAAAAAA", "Legacy Bank", "DE"])
    wb.save(path)
    assert _metadata(str(path)) == [(
        "AAAAAAAAAAAAAAAAAAAA", "Legacy Bank", "DE", False, [],
    )]
