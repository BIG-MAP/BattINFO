"""Benchmark bulk save_record throughput (beta-hardening 3.4).

Saves one cell spec and N cell instances referencing it into a fresh temp
source root, and reports records/second — the plan's target is >=1,000/s on
N=400 (baseline before the bulk-save session: 15-20/s).

Usage:
    uv run python scripts/bench_bulk_save.py [N] [--no-session]
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from battinfo import api  # noqa: E402


def _uid(i: int) -> str:
    # 16 chars from the id-safe alphabet (no i/l/o/u), varying per record.
    alphabet = "0123456789abcdefghjkmnpqrstvwxyz"
    digits = []
    value = i + 1
    while value:
        value, rem = divmod(value, 32)
        digits.append(alphabet[rem])
    return ("".join(digits) + "2m4p8t3x6nq57d9k")[:16]


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 400
    use_session = "--no-session" not in sys.argv

    with tempfile.TemporaryDirectory(prefix="battinfo-bench-") as tmp:
        root = Path(tmp) / "examples"
        spec = api.save_cell_spec(
            {
                "uid": "7d9k2m4p8t3x6nq5",
                "manufacturer": "BenchCo",
                "model": "BENCH-1",
                "chemistry": "Li-ion",
                "format": "cylindrical",
            },
            source_root=root,
        )
        spec_id = spec["id"]

        def run() -> float:
            start = time.perf_counter()
            for i in range(n):
                api.save_cell_instance(
                    {
                        "cell_spec_id": spec_id,
                        "serial_number": f"BENCH-{i:05d}",
                        "uid": _uid(i),
                    },
                    source_root=root,
                )
            return time.perf_counter() - start

        if use_session and hasattr(api, "bulk_save_session"):
            with api.bulk_save_session(root):
                elapsed = run()
            label = "with bulk_save_session"
        else:
            elapsed = run()
            label = "without session"

        rate = n / elapsed
        print(f"{n} records in {elapsed:.2f}s -> {rate:,.0f} records/s ({label})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
