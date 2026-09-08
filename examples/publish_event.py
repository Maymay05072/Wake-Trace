"""向本机 WakeTrace API 投递一个最小生活事件。"""

from __future__ import annotations

import argparse
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def parse_evidence(items: list[str]) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"invalid evidence item: {item!r}; expected key=value")
        evidence[key.strip()] = value.strip()
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765/world/events")
    parser.add_argument("--kind", default="external")
    parser.add_argument("--summary", required=True)
    parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="可重复提供；只传本次醒来必要的最小证据",
    )
    args = parser.parse_args()

    token = os.environ.get("WAKETRACE_ADMIN_TOKEN", "").strip()
    if not token:
        parser.error("WAKETRACE_ADMIN_TOKEN is required")

    try:
        evidence = parse_evidence(args.evidence)
    except ValueError as exc:
        parser.error(str(exc))

    body = json.dumps(
        {"kind": args.kind, "summary": args.summary, "evidence": evidence},
        ensure_ascii=False,
    ).encode()
    request = Request(
        args.url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            print(response.read().decode())
    except HTTPError as exc:
        raise SystemExit(f"WakeTrace returned HTTP {exc.code}: {exc.read().decode()}") from exc
    except URLError as exc:
        raise SystemExit(f"could not reach WakeTrace: {exc.reason}") from exc


if __name__ == "__main__":
    main()
