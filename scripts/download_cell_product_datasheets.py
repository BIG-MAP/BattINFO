from __future__ import annotations

import argparse
import csv
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def slug(name: str) -> str:
    name = name.strip()
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^A-Za-z0-9_.-]", "", name)
    return name


def normalize_header(header: list[str]) -> list[str]:
    return [h.strip().lstrip("\ufeff") for h in header]


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    rows = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=";")
        header = normalize_header(next(reader))
        idx = {name: i for i, name in enumerate(header)}
        for row in reader:
            if idx.get("source", -1) >= len(row):
                continue
            source = row[idx["source"]].strip()
            if not source:
                continue
            manufacturer = row[idx.get("manufacturer", 0)].strip() if "manufacturer" in idx else ""
            model = row[idx.get("model", 1)].strip() if "model" in idx else ""
            rows.append(
                {
                    "manufacturer": manufacturer,
                    "model": model,
                    "source": source,
                }
            )
    return rows


def infer_ext(url: str, content_type: str | None) -> str:
    suffix = Path(url).suffix
    if suffix:
        return suffix
    if content_type:
        if "pdf" in content_type:
            return ".pdf"
        if "html" in content_type:
            return ".html"
    return ".pdf"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--dest", required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--domain", default=None)
    parser.add_argument("--log", default=None)
    args = parser.parse_args()

    mapping = {
        "LG Chem": "LG",
        "Samsung SDI": "SAMSUNG",
        "Lithium Werks": "LITHIUMWERKS",
    }

    rows = load_rows(Path(args.csv))
    if args.domain:
        rows = [row for row in rows if args.domain in row["source"]]
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    end = min(args.start + args.limit, len(rows))
    print(f"Downloading rows {args.start}..{end - 1} of {len(rows)}")

    log_path = Path(args.log) if args.log else None
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(line: str) -> None:
        if log_path:
            log_path.write_text(log_path.read_text(encoding="utf-8") + line + "\n", encoding="utf-8") if log_path.exists() else log_path.write_text(line + "\n", encoding="utf-8")

    for idx in range(args.start, end):
        row = rows[idx]
        url = row["source"]
        manufacturer = mapping.get(row["manufacturer"], row["manufacturer"] or "Unknown")
        model = row["model"] or "unknown"
        base = f"{slug(manufacturer)}__{slug(model)}"

        attempt = 0
        while attempt <= args.retries:
            attempt += 1
            try:
                req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(req, timeout=args.timeout) as resp:
                    content_type = resp.headers.get("Content-Type")
                    data = resp.read()
                ext = infer_ext(url, content_type)
                target = dest / f"{base}{ext}"
                target.write_bytes(data)
                print(f"OK: {base}{ext}")
                log(f"OK,{url},{target}")
                break
            except (HTTPError, URLError, TimeoutError, ConnectionError) as exc:
                if attempt > args.retries:
                    print(f"FAIL: {url} ({exc})")
                    log(f"FAIL,{url},{exc}")
                else:
                    time.sleep(5)

        if args.delay:
            time.sleep(args.delay)


if __name__ == "__main__":
    main()
