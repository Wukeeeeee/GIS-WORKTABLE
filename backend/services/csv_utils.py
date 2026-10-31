"""Shared CSV export helpers."""

import re


def write_formula_safe_csv(frame, path):
    """Write spreadsheet-safe CSV while preserving original column value types."""
    import csv
    import pandas as pd

    def neutralize(value):
        if isinstance(value, str) and re.match(r'^\s*[=+\-@＝＋－＠]|^[\t\r\n]', value):
            return '\t' + value
        return value

    safe_frame = frame.copy()
    safe_frame.columns = [neutralize(column) for column in safe_frame.columns]
    for column in safe_frame.columns:
        safe_frame[column] = pd.Series(
            [neutralize(value) for value in safe_frame[column].tolist()],
            index=safe_frame.index,
            dtype=object,
        )
    safe_frame.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_ALL)
