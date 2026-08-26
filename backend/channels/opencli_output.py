"""Small parsers for OpenCLI subprocess output."""

import json


def parse_opencli_json(raw: str) -> list[dict]:
    json_start = next((i for i, ch in enumerate(raw) if ch in ("{", "[")), None)
    if json_start is None:
        raise ValueError(f"No JSON found in output: {raw[:200]!r}")
    # OpenCLI may append an update notice after otherwise valid JSON output.
    # Decode only the first JSON value instead of rejecting a harmless suffix.
    data, _ = json.JSONDecoder().raw_decode(raw[json_start:])
    return data if isinstance(data, list) else [data]
