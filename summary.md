# Page-Cache Fairness Benchmark — How It Works & How To Run It

This document explains, in detail, **what this benchmark does, how the code is
structured, what it measures, and the exact step-by-step commands to run the
experiments on a Linux host.**

It accompanies the research spec in `BENCHMARK.md` (usage/thesis) and the
implementation plan in `README.md` (phased TODO checklist). Where those two
describe *what* to build, this file describes *what was built here* and *how to
operate it*.

> **Platform:** the interference experiments require **Linux with cgroup v2**.
> Everything cgroup/PSI/`memory.stat`/`/proc/vmstat`/`iostat`-related is
> Linux-only; on macOS the binary builds and the fio command construction works,
> but the sampler, cgroup setup, and iostat logging all no-op. Use macOS only to
> iterate on the code.

---

## 1. The question the benchmark answers

Two tenants share one machine's Linux page cache:

- **Tenant A — the victim (`client1_steady`)**: a latency-sensitive, rate-limited
  random reader whose hot set *fits* in cache. We measure its **p99 read
  latency**.
- **Tenant B — the noisy neighbor (`client2_noisy`)**: a workload that pollutes
  the cache and/or dirties pages.

The thesis decomposes A's p99 spike into two mechanisms:

```
A's p99 spike = (A's cache-miss rate) × (baseline_read + writeback_queue_delay(B))
                └─────── Mechanism 1 ───────┘   └────────── Mechanism 2 ──────────┘
```

- **Mechanism 1 — eviction only.** B runs a large **clean** sequential scan
  (`b_scan_clean`), fills the LRU, evicts A's hot pages; A re-faults them from
  disk. No writeback involved.
- **Mechanism 2 — eviction + dirty writeback.** B runs **buffered writes**
  (`b_randwrite_dirty`); it evicts A's pages **and** produces dirty pages whose
  flushes land in the I/O queue ahead of A's read misses, inflating each miss.

**Headline comparison:** A's p99 under Mechanism 1 vs Mechanism 2 *at the same
eviction rate*. If the writer case is worse, dirty writeback amplifies the miss
penalty beyond what memory sizing alone can fix — the core result.

---

## 2. Files in this project

| File | Role |
|---|---|
| `benchmark.c` | The whole harness: config parsing, fio command building, cgroup setup, run orchestration, telemetry sampling. |
| `fairness_configs.ini` | Workload definitions: victim + every B variant + baselines. |
| `cgroup_shared.ini` | Shared-pool cgroup layout (2G parent cap; both tenants under it). |
| `cgroup_isolated.ini` | Isolated layout (`memory.low` floor for the victim, no hard cap on B). |
| `Makefile` | Build + convenience run targets. |
| `benchmark_analysis.py` | Reads a results dir and prints p99, refault deltas, dirty-page peaks, PSI stalls. |
| `benchmark_results/` | Output (created on first run). |
| `summary.md` | This document. |

---

## 3. How `benchmark.c` is structured

The program is a single C11 file organized into clear sections. Reading
top-to-bottom:

1. **Configuration model** — `PhaseConfig` (one I/O phase), `ClientConfig` (a
   tenant with N phases), `CgroupConfig`/`CgroupSet` (cgroup layout).
2. **INI parsing** — `parse_config()` reads `fairness_configs.ini` into
   `ClientConfig`s. Keys are either bare (`file_size`) or **phase-prefixed**
   (`phase_0_pattern`, `phase_1_rate_iops`, …). `apply_phase_key()` routes each
   key to the right `PhaseConfig` field.
3. **cgroup setup** — `parse_cgroup_config()` reads the cgroup `.ini`;
   `setup_cgroups()` creates the cgroup directories (with `mkdir -p` semantics)
   and writes `memory.max` / `memory.low` / `io.weight`.
   `enable_controllers()` writes `+memory +io` into each parent's
   `cgroup.subtree_control` so nested cgroups actually expose those knobs.
4. **memory.stat snapshots** — `record_memstat()` reads
   `workingset_refault_file` before and after each phase and writes the
   **delta** to `memstat/<client>_<mode>.csv`.
5. **Telemetry sampler** — a forked child (`run_sampler()`) that every second
   samples:
   - `/proc/vmstat`: `nr_dirty`, `nr_writeback`, `pgpgin`, `pgscan_kswapd`
     → `dirty/vmstat_<mode>.csv`
   - per-cgroup `memory.stat`: `file_dirty`, `file_writeback`
     → `dirty/<cg>_<mode>_dirty.csv`
   - per-cgroup PSI: `memory.pressure` + `io.pressure` `some` totals
     → `psi/<cg>_<mode>.csv`
6. **iostat logger** — `start_iostat()` forks `iostat -dx 1` into
   `iostat/run_<mode>.iostat`.
7. **fio command builder** — `build_fio_cmd()` turns a `PhaseConfig` into an
   `fio` command line, including `--output-format=json+` so the JSON contains
   `clat_ns.percentile` (p99/p999).
8. **Test-file management** — `ensure_test_file()` pre-creates each tenant's
   file with `fio --create_only` if missing; `drop_caches()` flushes the page
   cache before each cached-mode phase.
9. **Run orchestration** — `run_clients()` pre-creates files, starts the
   sampler + iostat, then for each phase: drops caches, takes a "before"
   memstat snapshot, forks all clients' fio for that phase concurrently
   (each joining its cgroup via `cgroup.procs`), waits, takes an "after"
   snapshot (computing the refault delta), and finally writes a line to
   `summary.txt`.
10. **CLI** — `main()` parses options and dispatches `dual` / `all` / a single
    named workload.

### The three previously-planned features (now implemented)

These were listed as TODOs ("planned fields") in the spec and are wired end to
end. Search `benchmark.c` for the tags:

- **`[TODO-1]` `phase_N_random_distribution`** — e.g. `zipf:1.2`. Emitted as
  `--random_distribution=zipf:1.2`. Skews the victim's hot set so refaults
  actually hurt (uniform-random over a huge file never reuses pages, making
  eviction "free" and hiding the effect).
- **`[TODO-2]` `phase_N_fdatasync` / `phase_N_fsync`** — flush cadence. Emitted
  as `--fdatasync=N` / `--fsync=N`. `b_checkpoint` uses `fdatasync=1000`
  (periodic big flush bursts, PostgreSQL/etcd style); `b_wal_append` uses
  `fdatasync=32` (frequent small flushes, WAL style).
- **`[TODO-3]` `/proc/vmstat` + per-cgroup `file_dirty` sampling** — the 1 Hz
  sampler above. Directly measures dirty-page accumulation and writeback, the
  observable signature of Mechanism 2.

---

## 4. What gets measured (and where it lands)

After a run, `benchmark_results/` (or your `-o <dir>`) contains:

```
benchmark_results/
├── <client>_<mode>_p<phase>.json   # raw fio JSON+ (has clat_ns.percentile.99)
├── summary.txt                     # one line per (mode, client-set) run
├── iostat/run_<mode>.iostat        # iostat -dx 1 device stats
├── psi/<cg>_<mode>.csv             # ts, mem_some_total_us, io_some_total_us
├── memstat/<client>_<mode>.csv     # phase, when, workingset_refault_file, delta
└── dirty/
    ├── vmstat_<mode>.csv           # ts, nr_dirty, nr_writeback, pgpgin, pgscan_kswapd
    └── <cg>_<mode>_dirty.csv       # ts, file_dirty, file_writeback
```

| Metric | Meaning | Source |
|---|---|---|
| **p99 / p999 read latency (µs)** | The objective. Lower & flatter under interference = better isolation. | fio `clat_ns.percentile` |
| **`workingset_refault_file_delta`** | Pages a tenant evicted and had to re-fault per phase (× 4 KiB ≈ bytes re-read). Direct eviction-churn measure. | `memstat/` |
| **PSI `some` stall (memory, io)** | Per-cgroup time stalled on memory / io. | `psi/` |
| **`nr_dirty` / `nr_writeback`, `file_dirty`** | Dirty-page accumulation & writeback — Mechanism 2's fingerprint. | `dirty/` |
| **iostat r/w latency & queue depth** | Surfaces writeback contention at the device. | `iostat/` |
| **IOPS / BW** | Secondary throughput context, not the objective. | fio JSON |

---

## 5. Prerequisites

```bash
# Ubuntu / Debian
sudo apt-get install fio gcc make sysstat   # sysstat provides iostat

# Confirm cgroup v2 is the active hierarchy (should print "cgroup2fs")
stat -fc %T /sys/fs/cgroup

# Confirm PSI is enabled (file should exist)
cat /proc/pressure/memory
```

Also ensure enough disk: B's files are 2–4× the cache cap, and Case 4 uses a
48G file. `df -h .` before running.

---

## 6. Build

```bash
make            # produces ./benchmark
make clean      # remove the binary
```

> **Makefile note:** the run-everything target is `make run-all` (not
> `make benchmark`) because `benchmark` is also the binary's filename and Make
> cannot have a phony target collide with a real file of the same name.

---

## 7. Quickstart (the primary experiment)

```bash
# A + B interference in cached mode, shared 2G cache pool.
# sudo is required for drop_caches + cgroup setup.
sudo ./benchmark --cgroup-config cgroup_shared.ini -m cached dual

# Analyze
./benchmark_analysis.py benchmark_results/
cat benchmark_results/summary.txt
```

> **Always run writer-B pairings with `-m cached`.** In `direct` mode fio
> bypasses the page cache, produces no dirty pages, and Mechanism 2 vanishes.

---

## 8. Step-by-step: the full experiment progression

Each step changes **one** variable from the previous, so any change in A's p99
or refault delta is attributable to that knob. Send each to its own results dir
with `-o` so the analysis script can compare them side by side.

### Step 0 — Baseline: victim alone

```bash
sudo ./benchmark -m cached -o results/baseline victim_alone
```
*Expect:* flat p99, `workingset_refault_file_delta ≈ 0`. This is the reference
every later delta subtracts from.

### Step 1 — Isolated baselines (each client alone)

```bash
sudo ./benchmark -m cached -o results/case1_a client1_steady
sudo ./benchmark -m cached -o results/case1_b client2_noisy
```
*Isolates:* standalone p99 / throughput per client; confirms B isn't
self-throttled.

### Step 2 — Concurrent, WITH isolation

```bash
sudo ./benchmark --cgroup-config cgroup_isolated.ini -m cached -o results/case2 dual
```
*Isolates:* whether cgroup `memory.low` protection keeps A's p99 ≈ baseline when
both run together. *Expect:* p99 stays near baseline.

### Step 3 — Concurrent, NO memory limits (raw interference)

```bash
sudo ./benchmark --no-cgroup -m cached -o results/case3 dual
```
*Isolates:* interference with nothing protecting A. *Expect:* A's p99 spikes.

### Step 4 — Heavy eviction pressure (B ≫ cache under a tiny cap)

Edit `cgroup_shared.ini` so the parent cap is `512M`, and set
`client2_noisy`'s `file_size = 48G` with `phase_0_pattern = randread` in
`fairness_configs.ini`. (For strict single-variable rigor, split into 4a =
file-size change only, 4b = add the 512M cap.)

```bash
sudo ./benchmark --cgroup-config cgroup_shared.ini -m cached -o results/case4 dual
```
*Expect:* maximal eviction of A; large `workingset_refault_file_delta` for A.

### Step 5 — Cap only the victim

Set `[client1_steady] memory.max = 1G` in `cgroup_shared.ini`.

```bash
sudo ./benchmark --cgroup-config cgroup_shared.ini -m cached -o results/case5 dual
```
*Isolates:* whether limiting **A** helps or hurts A's p99.

### Step 6 — Cap only the aggressor (the standard mitigation)

Set `[client2_noisy] memory.max = 1G` in `cgroup_shared.ini`.

```bash
sudo ./benchmark --cgroup-config cgroup_shared.ini -m cached -o results/case6 dual
```
*Isolates:* whether capping **B** bounds A's p99.

### Step 7 — The headline: Mechanism 1 vs Mechanism 2 at equal eviction

Run the victim against a clean scanner, then against a buffered writer, matching
their eviction rate (tune `phase_0_rate_iops`):

```bash
# Point client2_noisy at b_scan_clean's params, or run the pairing directly:
sudo ./benchmark --cgroup-config cgroup_shared.ini -m cached -o results/scan  dual   # B = clean scan
# then swap client2_noisy to the b_randwrite_dirty params and:
sudo ./benchmark --cgroup-config cgroup_shared.ini -m cached -o results/write dual   # B = dirty writer

./benchmark_analysis.py results/scan
./benchmark_analysis.py results/write
```
*Expect:* at the same eviction rate, `results/write` shows **higher** A p99 and
elevated `nr_writeback` — the dirty-writeback amplification.

### Intensity sweep (Fig 1)

Run `b_scan_clean` and `b_randwrite_dirty` across `rate_iops` = 1k / 5k / 20k /
50k / unlimited, one results dir each, and plot B's intensity (X) vs A's p99 (Y),
one curve per mechanism.

---

## 9. Command-line reference

```
./benchmark [options] <workload | dual | all>

  <workload>   Run a single [section] from the config (baseline/characterization)
  dual         Run client1_steady (A) + client2_noisy (B) concurrently (primary)
  all          Run every [section] in the config

  -c, --config PATH        Workload ini            (default: fairness_configs.ini)
      --cgroup-config PATH  cgroup layout ini (enables cgroup setup)
      --no-cgroup          Disable cgroup setup (shared page-cache pool)
      --no-psi             Disable PSI sampling
  -m, --mode MODE          cached | direct | both  (default: both)
  -o, --output DIR         Results dir             (default: benchmark_results)
  -v, --verbose            Verbose logging (prints each fio command)
  -h, --help               Help
```

---

## 10. Configuring workloads

Sections in `fairness_configs.ini`. Sizes are chosen **relative to the cgroup
cap** (2G shared), not as fixed absolutes. Keys are phase-prefixed
(`phase_N_...`) so a section can define multiple phases.

```ini
[client1_steady]                       ; Tenant A — the victim
description = Hot-set random reader; measure p99
file_size = 1G                         ; ~0.5x the 2G cap (fits in cache)
phase_0_pattern = randread
phase_0_block_size = 4k
phase_0_rate_iops = 5000               ; rate-limit keeps p99 an SLO signal
phase_0_iodepth = 1
phase_0_numjobs = 4                    ; prefer numjobs over iodepth for cached
phase_0_runtime = 60
phase_0_ioengine = libaio
phase_0_random_distribution = zipf:1.2 ; [TODO-1] skew so refaults hurt

[client2_noisy]                       ; Tenant B — buffered dirty writer (Mech 2)
description = Random writer generating dirty writeback
file_size = 8G                         ; ~4x the cap
phase_0_pattern = randwrite
phase_0_block_size = 4k
phase_0_rate_iops = 20000
phase_0_iodepth = 32
phase_0_numjobs = 4
phase_0_runtime = 60
phase_0_ioengine = libaio
```

**B variants also defined** (swap into `client2_noisy` or run standalone):
`b_scan_clean` (Mech 1, 1M sequential read), `b_randwrite_dirty` (Mech 2),
`b_mixed` (`randrw`, `rwmixread=50`), `b_checkpoint` (`fdatasync=1000`),
`b_wal_append` (`fdatasync=32`).

**Recognized phase keys:** `pattern`, `block_size`, `ioengine`, `rate_iops`,
`iodepth`, `numjobs`, `runtime`, `rwmixread`, `random_distribution`,
`fdatasync`, `fsync`. Bare (non-phased) keys are applied to phase 0.

---

## 11. Interpreting the analysis output

`./benchmark_analysis.py <dir>` prints four sections:

- **READ LATENCY** — per-JSON p99/p999 + IOPS/BW. Compare A's p99 across cases.
- **WORKING SET REFAULTS** — per-phase refault delta per cgroup, pages + MiB.
  Bigger delta = more eviction churn inflicted.
- **DIRTY-PAGE PRESSURE** — peak `nr_dirty`/`nr_writeback`/`pgpgin`/
  `pgscan_kswapd` and per-cgroup `file_dirty` — Mechanism 2's fingerprint.
- **PSI PRESSURE** — memory/io `some` stall accrued over the run (last − first
  total), in ms.

**What the thesis predicts you'll see:**
1. A alone → flat p99, ~100% cache hit.
2. A + `b_scan_clean` → p99 rises from refaults (Mechanism 1).
3. A + `b_randwrite_dirty` → p99 rises **further** at the same eviction rate
   (Mechanism 2), with elevated `nr_writeback`.
4. A + B under `memory.low` → partial recovery for the scanner; **residual**
   p99 elevation for the writer — motivating cross-layer memory↔I/O coordination.

---

## 12. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `warning: open .../memory.max: ...` | Run under `sudo`; ensure cgroup v2 (`stat -fc %T /sys/fs/cgroup` = `cgroup2fs`). |
| cgroup knobs don't stick / files missing | Parent's `cgroup.subtree_control` lacks the controller. The harness writes `+memory +io`, but a restrictive systemd delegation can still block it; run inside a delegated scope (`systemd-run --user -p Delegate=yes ...`) or as root. |
| Empty `psi/` dir | PSI disabled in kernel, or you passed `--no-psi`. Check `cat /proc/pressure/memory`. |
| Empty `iostat/` | `sysstat` not installed (`apt-get install sysstat`). |
| `drop_caches` warning | Needs root; run with `sudo`. |
| p99 looks like saturation, not SLO | The victim must be rate-limited (`rate_iops`); an unlimited victim measures throughput, not an SLO tail. |
| Refault delta ≈ 0 despite B thrashing | Victim using uniform random over a huge file — set `random_distribution = zipf:1.2` and size its file to ~0.5× cap. |

---

## 13. Relationship to the repo's own docs

- `BENCHMARK.md` — the usage/thesis spec (what to run, expected outcomes).
- `README.md` — the phased implementation plan (Phase 0–6 checklist). This
  build corresponds to that plan collapsed into a single `benchmark.c` +
  `benchmark_analysis.py` rather than the multi-file `src/*.c` layout it
  sketches; the config keys, workloads, telemetry, and experiment cases match.
