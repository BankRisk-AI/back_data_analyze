"""Vocabulary and limits of the processing module (no dependency on the database or the web)."""

KEY_COLUMNS = ("lei_code", "nsa", "period", "item")
LABEL_COLUMN = "label"
MEASURE_COLUMN = "amount"
ANNOTATION_COLUMNS = ("footnote",)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 1000
DEFAULT_BINS = 30
MAX_BINS = 200
DEFAULT_SCATTER_POINTS = 2000
MAX_SCATTER_POINTS = 5000
DEFAULT_TOP_VALUES = 5
MAX_TOP_VALUES = 20
MAX_EXAMPLES = 5
QUERY_TIMEOUT_SECONDS = 30
TOP_VALUES_MAX_DISTINCT = 200          # top values are listed only for columns with at most this many distinct values

AGGREGATIONS = ("single", "sum", "mean", "min", "max")
SCALES = ("linear", "log")
CLIPS = ("none", "p01-p99", "iqr")
SEVERITIES = ("error", "warning", "info")
SORT_ORDERS = ("asc", "desc")

VALIDATION_JOB_KIND = "validate_data"
VALIDATION_STEP = "validation_report"


def column_role(name: str) -> str:
    """Role of a staging column: key, label, measure, annotation or dimension (everything else in an EBA data file)."""
    if name in KEY_COLUMNS:
        return "key"
    if name == LABEL_COLUMN:
        return "label"
    if name == MEASURE_COLUMN:
        return "measure"
    if name in ANNOTATION_COLUMNS:
        return "annotation"
    return "dimension"
