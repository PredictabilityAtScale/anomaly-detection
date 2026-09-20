import csv
import io
import json
import sys
from pathlib import Path
from .contracts import Dataset


def read_text(path, max_bytes):
    if path == "-":
        raw = sys.stdin.buffer.read(max_bytes + 1)
    else:
        with Path(path).open("rb") as stream:
            raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("input exceeds max_bytes")
    return raw.decode("utf-8-sig")


def load_json(text):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError(f"duplicate JSON key: {k}")
            result[k] = v
        return result
    def bad_constant(value):
        raise ValueError(f"nonfinite JSON constant: {value}")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=bad_constant)


def csv_dataset(text, time_column, value_column, frequency, timezone=None, units=None):
    if not value_column:
        raise ValueError("CSV requires --value")
    if bool(time_column) != bool(frequency):
        raise ValueError("CSV requires --time and --frequency together, or neither for positional values")
    if timezone and not time_column:
        raise ValueError("--timezone requires --time and --frequency")
    if time_column and time_column == value_column:
        raise ValueError("time and value columns must differ")
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    if len(headers) != len(set(headers)):
        raise ValueError("duplicate CSV column names")
    if value_column not in headers or (time_column and time_column not in headers):
        raise ValueError("selected CSV columns do not exist")
    timestamps, values = ([] if time_column else None), []
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f"malformed CSV row {reader.line_num}")
        # Extra varying columns can encode entities or mixed units. Reject rather
        # than accidentally combining them; constant metadata columns are allowed.
        if timestamps is not None:
            timestamps.append(row[time_column])
        cell = row[value_column].strip()
        values.append(None if cell == "" else float(cell))
    reader = csv.DictReader(io.StringIO(text))
    selected = {value_column} | ({time_column} if time_column else set())
    extras = {h: set() for h in headers if h not in selected}
    for row in reader:
        for h in extras:
            extras[h].add(row[h])
    if any(len(v) > 1 for v in extras.values()):
        raise ValueError("varying unmapped CSV columns: select one entity and unit, then supply only time/value columns")
    return Dataset(id="series", timestamps=timestamps, values=values, frequency=frequency, timezone=timezone, units=units)


def write_result(text, path=None, overwrite=False):
    if path:
        with Path(path).open("w" if overwrite else "x", encoding="utf-8", newline="\n") as stream:
            stream.write(text + "\n")
    else:
        print(text)
