"""CSV writer for ingest tests (unique module name: importable from any test directory)."""

HEADER = "LEI_Code,NSA,Period,Item,Label,Amount,footnote\n"


def write_csv(path, rows, encoding="cp1252", header=HEADER):
    with open(path, "w", encoding=encoding, newline="") as file:
        file.write(header)

        for row in rows:
            file.write(row + "\n")

    return str(path)
