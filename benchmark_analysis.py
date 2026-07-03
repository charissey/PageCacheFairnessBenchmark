#!/usr/bin/env python3
"""benchmark_analysis.py — summarize page-cache fairness results.

Reads a results directory produced by ./benchmark and reports:
  * Tenant A p99 / p999 read latency (from fio clat_ns.percentile)
  * IOPS / bandwidth (secondary context)
  * workingset_refault_file_delta per phase per cgroup (from memstat/)
  * dirty-page pressure (from dirty/ — [TODO-3] vmstat + file_dirty samples)

Usage: ./benchmark_analysis.py <results_dir>
"""

import csv
import json
import os
import sys
from glob import glob


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  ! could not read {path}: {e}")
        return None


def us(ns):
    return ns / 1000.0


def report_latency(results_dir):
    print("\n## \U0001f4c8 READ LATENCY (Tenant A objective)")
    print("=" * 50)
    files = sorted(glob(os.path.join(results_dir, "*.json")))
    if not files:
        print("  (no fio json found)")
        return
    for path in files:
        data = load_json(path)
        if not data or "jobs" not in data:
            continue
        name = os.path.basename(path)
        for job in data["jobs"]:
            clat = job.get("read", {}).get("clat_ns", {})
            pct = clat.get("percentile", {})
            p99 = pct.get("99.000000")
            p999 = pct.get("99.900000")
            iops = job.get("read", {}).get("iops", 0.0)
            bw = job.get("read", {}).get("bw", 0.0)  # KiB/s
            line = f"  {name} [{job.get('jobname','?')}]:"
            if p99 is not None:
                line += f" p99={us(p99):.1f}us"
            if p999 is not None:
                line += f" p999={us(p999):.1f}us"
            line += f" iops={iops:.0f} bw={bw/1024:.1f}MiB/s"
            print(line)


def report_refaults(results_dir):
    print("\n## \U0001f501 WORKING SET REFAULTS (page-cache eviction churn)")
    print("=" * 50)
    memstat_dir = os.path.join(results_dir, "memstat")
    files = sorted(glob(os.path.join(memstat_dir, "*.csv")))
    if not files:
        print("  (no memstat csv found — Linux/cgroup v2 only)")
        return
    for path in files:
        name = os.path.basename(path).replace(".csv", "")
        print(f"\n**{name}:**")
        with open(path) as f:
            for row in csv.DictReader(f):
                if row.get("when") == "after":
                    delta = row.get("workingset_refault_file_delta", "-1")
                    try:
                        d = int(delta)
                    except ValueError:
                        d = -1
                    if d >= 0:
                        print(f"  phase {row['phase']}: {d:>12,} pages "
                              f"({d * 4096 / (1024*1024):8.1f} MiB)")


def report_dirty(results_dir):
    """[TODO-3] /proc/vmstat + per-cgroup file_dirty time series."""
    print("\n## \U0001f4a7 DIRTY-PAGE PRESSURE (vmstat + per-cgroup file_dirty)")
    print("=" * 50)
    dirty_dir = os.path.join(results_dir, "dirty")
    files = sorted(glob(os.path.join(dirty_dir, "*.csv")))
    if not files:
        print("  (no dirty csv found — Linux only)")
        return
    for path in files:
        name = os.path.basename(path).replace(".csv", "")
        peaks = {}
        with open(path) as f:
            reader = csv.DictReader(f)
            fields = [c for c in (reader.fieldnames or []) if c != "ts"]
            for row in reader:
                for c in fields:
                    try:
                        v = int(row[c])
                    except (ValueError, TypeError):
                        continue
                    peaks[c] = max(peaks.get(c, 0), v)
        summary = "  ".join(f"{c} peak={v:,}" for c, v in peaks.items())
        print(f"  {name}: {summary}")


def report_psi(results_dir):
    """PSI 'some' stall accrued over the run = last total - first total (us)."""
    print("\n## \U0001f6a6 PSI PRESSURE (memory + io 'some' stall over run)")
    print("=" * 50)
    psi_dir = os.path.join(results_dir, "psi")
    files = sorted(glob(os.path.join(psi_dir, "*.csv")))
    if not files:
        print("  (no psi csv found — Linux only)")
        return
    for path in files:
        name = os.path.basename(path).replace(".csv", "")
        rows = []
        with open(path) as f:
            for row in csv.DictReader(f):
                rows.append(row)
        if not rows:
            print(f"  {name}: (empty)")
            continue

        def accrued(col):
            vals = [int(r[col]) for r in rows
                    if r.get(col, "-1").lstrip("-").isdigit() and int(r[col]) >= 0]
            return (vals[-1] - vals[0]) if len(vals) >= 2 else -1

        mem = accrued("mem_some_total_us")
        io = accrued("io_some_total_us")
        parts = []
        if mem >= 0:
            parts.append(f"memory={mem/1000:.1f}ms")
        if io >= 0:
            parts.append(f"io={io/1000:.1f}ms")
        print(f"  {name}: {'  '.join(parts) if parts else '(no data)'}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    results_dir = sys.argv[1]
    if not os.path.isdir(results_dir):
        print(f"error: {results_dir} is not a directory")
        sys.exit(1)

    print(f"# Page-Cache Fairness Analysis — {results_dir}")
    report_latency(results_dir)
    report_refaults(results_dir)
    report_dirty(results_dir)
    report_psi(results_dir)
    print()


if __name__ == "__main__":
    main()
