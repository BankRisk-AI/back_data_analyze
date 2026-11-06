"""Catalogue of the validation rules: what each checks and how serious a failure is. The SQL lives in infrastructure."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    severity: str
    description: str


RULES: tuple[Rule, ...] = (
    Rule("V01", "Required values present", "error", "lei_code, period and item must not be empty."),
    Rule("V02", "No duplicate keys", "error", "A row is identified by LEI, country, period, item and every dimension column; the same identity must not appear twice."),
    Rule("V03", "Amounts are numbers", "error", "Every non-empty amount must be a number."),
    Rule("V04", "Amounts present", "warning", "Rows with an empty amount carry no information."),
    Rule("V05", "Period format", "error", "period must be YYYYMM with a month from 01 to 12."),
    Rule("V06", "Quarter-end periods", "warning", "The EBA files only report quarter ends (03, 06, 09, 12)."),
    Rule("V07", "LEI format", "error", "Banks are identified by a 20-character alphanumeric LEI (the aggregate bucket is exempt)."),
    Rule("V08", "Country code", "warning", "nsa should be a two-letter upper-case country code."),
    Rule("V09", "One label per item", "warning", "An item should keep the same label in every row."),
    Rule("V10", "Panel balance", "info", "The number of banks should not change between periods; the banks that appear or disappear are listed."),
    Rule("V11", "Outliers", "info", "Amounts beyond 3 x IQR from the quartiles of their (item, period); listed, never removed."),
    Rule("V12", "Aggregate bucket", "info", "Rows of 'All other banks' (LEI of X characters or country OT) are counted; the next step excludes them."),
    Rule("V13", "No empty columns", "warning", "A column with no value at all in the file is probably misplaced or misnamed."),
)
RULES_BY_ID = {r.id: r for r in RULES}
