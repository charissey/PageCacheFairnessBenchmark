# Pagecache Fairness Benchmark (C)

This repository contains a focused benchmarking suite to measure **page-cache
performance isolation failures** between co-located tenants — specifically the
**p99 read-latency spike** a latency-sensitive reader (Tenant A) suffers when a
noisy neighbor (Tenant B) shares the page cache.

## 🎯 Purpose

The benchmark exists to validate the two-component model of the p99 spike

```
A's p99 spike = (A's cache-miss rate) × (baseline_read + writeback_queue_delay(B))
```

The experiments isolate the **two interference mechanisms**:

- **Mechanism 1 — eviction only:** B runs a large *clean* sequential scan, fills
  the LRU, and evicts A's hot pages. A re-faults them from disk. No writeback.
- **Mechanism 2 — eviction + dirty writeback:** B runs *buffered writes*, so it
  both evicts A's pages **and** generates dirty pages whose flushes land in the
  I/O queue ahead of A's reads, inflating A's per-miss latency.

The headline result compares A's p99 under Mechanism 1 vs Mechanism 2 **at the
same eviction rate** — if the writer case is worse, that confirms dirty
writeback amplifies the miss penalty beyond what memory sizing alone can fix.

> The old framing ("small sequential workloads win, large random workloads lose")
> is a side effect, not the object of study. Workloads below are organized around
> **victim + noisy-neighbor pairings**, not around a single-workload sweep.

## 📁 Project Structure

```
pagecachefairnessbenchmark/
├── fairness_configs.ini           # Workload definitions (victim + B variants)
├── cgroup_shared.ini              # Shared-cache cgroup layout (2G pool)
├── cgroup_isolated.ini            # Isolated per-tenant cgroup layout
├── check_cgroups.sh               # Pre-flight cgroup v2 validation script
├── benchmark.c                    # C benchmark implementation
├── benchmark                      # Compiled C binary
├── Makefile                       # Build configuration
├── Dockerfile                     # Ubuntu image with fio + build deps
├── .dockerignore                  # Keep test files / results out of the image
├── benchmark_analysis.py          # Results analysis (fio + PSI + refaults)
├── results/             # Test results directory
│   ├── *.json                     # Raw fio output (per phase)
│   ├── iostat/                    # iostat -x logs
│   ├── psi/                       # Per-cgroup PSI time series (CSV)
│   └── memstat/                   # Per-cgroup memory.stat snapshots (CSV)
├── setup_test_files.sh            # One-time dense test_file_1G / test_file_8G
├── test_file_*                    # Reused size-tagged files (test_file_1G, …)
└── README.md                      # Research thesis and experiment plan
```

## Getting Started

### Prerequisites
- `fio` (I/O benchmark tool)
- `gcc` with C11 support
- `make` (build tool)
- `iostat` (I/O monitoring)
- Sufficient disk space for test files (~9 GB default; 48+ GB for Case 4)

### Install Dependencies (macOS)
```bash
brew install fio gcc make
```

### Install Dependencies (Ubuntu/Debian)
```bash
sudo apt-get update
sudo apt-get install fio gcc make sysstat
```

### Build the Benchmark
```bash
make
```

### Create test files (once)
```bash
# Dense test_file_1G + test_file_8G (~9 GB). Reused across all experiments.
make setup-files
# Or: ./setup_test_files.sh 1G 8G 48G   # add Case 4 size when needed
```
The harness also creates a missing/wrong-sized file on first use, but
pre-creating avoids paying fill cost inside a timed run.

### Running with Docker

The benchmark needs Linux **cgroup v2**, writable `/sys/fs/cgroup`, and
`/proc/sys/vm/drop_caches`. Use a privileged container with the host cgroup
namespace so nested cgroup setup matches `check_cgroups.sh`.

```bash
# Build the image (does not bake in multi-GB test files)
docker build -t pagecache-bench .

# Interactive shell — preferred while iterating on cases
docker run --rm -it --privileged --cgroupns=host \
  -v "$PWD:/bench" \
  -w /bench \
  pagecache-bench bash
```

Inside the container (root is enough; no `sudo`):

```bash
make                                    # rebuild if you bind-mounted the repo
./check_cgroups.sh --cgroup-config cgroup_shared.ini
./setup_test_files.sh 1G 8G             # once; ~9 GB on the bind mount
./benchmark --cgroup-config cgroup_shared.ini -m cached dual
./benchmark_analysis.py results/
```

One-shot dual run (results land on the host via the bind mount):

```bash
docker run --rm --privileged --cgroupns=host \
  -v "$PWD:/bench" -w /bench \
  pagecache-bench \
  ./benchmark --cgroup-config cgroup_shared.ini -m cached dual
```

On first run, every `memory.low`/`io.weight` write failed with `Permission 
denied`, and `cgroup.subtree_control` write failed with `Device or resource 
busy`.

Cause: the container's own shell (and PID 1) live *directly* in the
container's root cgroup (`/sys/fs/cgroup/cgroup.procs`). cgroup v2 enforces
a "no internal processes" rule — a cgroup can't both hold processes itself
*and* delegate controllers to children. Since our shell sits at the root,
the root can't enable `+memory +io` for its children until the shell is
moved out.

Fix — move the current shell into its own leaf cgroup first, then enable
controllers:

```bash
mkdir -p /sys/fs/cgroup/init
echo $$ > /sys/fs/cgroup/init/cgroup.procs
echo "+memory +io" > /sys/fs/cgroup/cgroup.subtree_control
```

Verified output after this:
```
$ cat /sys/fs/cgroup/cgroup.subtree_control
io memory
```

**Notes**
- Bind-mount the repo (`-v "$PWD:/bench"`) so `test_file_*` and
  `results/` persist on the host and survive container restarts.
- On **Docker Desktop (macOS/Windows)** the container runs in a Linux VM; you
  measure that VM’s page cache, not the Mac/Windows host. Prefer a native
  Linux host or VM for paper-quality I/O numbers.
- If `check_cgroups.sh` fails, confirm you passed both `--privileged` and
  `--cgroupns=host`.

## 📊 Workload Design

Workloads are grouped by the **role** they play in an experiment, not by a
read/write × iodepth grid. Sizes are expressed **relative to the cgroup memory
cap** (`memory.max`, 2G in `cgroup_shared.ini`) rather than as fixed absolutes,
because interference depends on working-set-to-cache ratio.

### Tenant A — the victim (what we measure)

`client1_steady`: 1G sequential `read`, 4k, rate-limited (`rate_iops=10000`, `numjobs=1`), cached mode. Report clat **p99**. Optional `phase_0_random_distribution = zipf:1.2` skews the hot set so refaults hurt.

### Tenant B — the noisy neighbor

`client2_noisy`: default **Mechanism 1** — 8G `randread`, 4k, buffered (`rate_iops=80000`, `numjobs=1`, `iodepth=32`). Edit `phase_0_*` in `[client2_noisy]` for other B behaviors:

| Pattern | bs | Mechanism |
|---------|-----|-----------|
| `read` (sequential) | 1M | **1** — LRU pollution, no writeback |
| `randread` | 4k | **1** — random read pressure |
| `randwrite` | 4k | **2** — eviction + dirty writeback |

### Baselines (Case 1)

| Run | Command | Purpose |
|-----|---------|---------|
| A alone | `./benchmark client1_steady` | Flat-p99 reference; Δp99 = (A+B) − this |
| B alone | `./benchmark client2_noisy` | Confirm B sustains its load without A |

## 🔬 Experiment Structure

The unit of experiment is a **dual-client pairing** (`dual` mode), run under the
four isolation conditions from the thesis:

| Condition | Setup | Expected outcome |
|---|---|---|
| Baseline | A alone (`client1_steady`) | p99 flat; cache-hit ≈ 100% |
| Interference | A + B, no isolation | A's p99 spikes; writer B worse than reader B at equal eviction |
| cgroup v2 | Separate per-tenant cgroups (`cgroup_isolated.ini`; uncomment `memory.low` on A to test protection) | Partial recovery with `memory.low`; residual p99 elevation under writer B |
| Proposed policy | A + B under proposed policy | A's p99 within SLO for both B variants |

**Key comparison:** edit `[client2_noisy]` to `randread` (or sequential `read`) vs `randwrite`, then run `dual` at the **same rate** → does dirty writeback add p99 beyond clean eviction?

**Intensity sweep (Fig 1):** sweep `client2_noisy` `phase_0_rate_iops` (e.g. 1k / 5k / 20k / 50k / unlimited) for read vs write B, plot B intensity (X) vs A p99 (Y).

### Axes that matter (and ones that don't)

- **Block size** is a first-class variable: `bs=1M` sequential = clean scan;
  `bs=4k` random = dirty writes. Do **not** fix everything at 4k.
- **Access distribution** matters: uniform random over a huge file never reuses
  pages, so eviction is free. Use `zipf` for the victim so refaults actually hurt.
- **Buffered vs direct:** writer B must run in **cached** mode — `direct=1`
  generates no dirty page cache and disables Mechanism 2.
- **`numjobs` over `iodepth`** for concurrency: buffered I/O degrades toward
  synchronous, so `iodepth` barely varies true concurrency in cached mode.
  Reserve `iodepth` for the `direct` no-cache baseline.

## 🧪 Experiment Cases (change one variable at a time)

These cases form a **controlled progression**: hold the two tenants
(`client1_steady`, `client2_noisy`), their patterns, runtime, and block size
fixed, and change **exactly one knob per step** so any change in A's p99 or
refault delta is attributable to that knob. Each case is a delta from the one
before it.

| Case | Name | Concurrency | cgroup / memory config | The single variable changed | What it isolates |
|---|---|---|---|---|---|
| 1 | Isolated Baselines | Each client **alone** | n/a (no sharing) | — (reference point) | Standalone p99 / throughput per client; the baseline all deltas subtract from |
| 2 | Isolated Clients | Concurrent | `cgroup_isolated.ini` (separate per-tenant cgroups) | +concurrency, **with** isolation | Whether separate cgroups keep p99 ≈ baseline when both run together |
| 3 | Shared Client 2 Random Read | Concurrent | shared, parent `memory.max = 512M` | B → 48G file, `randread`, under tiny shared cap | Heavy eviction pressure: B's working set ≫ cache |
| 4 | Shared Client 1 Limited | Concurrent | shared, `client1_steady memory.max = 1G` | cap the **victim's** memory | Whether limiting A (not B) helps or hurts A's p99 |
| 5 | Shared Client 2 Limited | Concurrent | shared, `client2_noisy memory.max = 1G` | cap the **aggressor's** memory | The standard mitigation: does capping B bound A's p99? |

### Running each case

```bash
# Case 1 — Isolated Baselines (run each client on its own, no contention)
sudo ./benchmark -v --drop-once --cgroup-config cgroup_isolated.ini -m cached -o results/client1 client1_steady
sudo ./benchmark -v --drop-once --cgroup-config cgroup_isolated.ini -m cached -o results/client2 client2_noisy

# Case 2 — Isolated Clients (concurrent, isolated cgroups)
sudo ./benchmark -v --drop-once --cgroup-config cgroup_isolated.ini -m cached -o results/cached_isolated dual

# Cases 3-5 — Shared with one cap changed (edit the cgroup .ini, then run)
sudo ./benchmark -v --drop-once --cgroup-config cgroup_shared.ini -m cached -o results/cached_dual dual
```

For Cases 3-5, change the single `memory.max` line in the cgroup config (keep
everything else identical to Case 3's shared layout):

```ini
# Case 4 — cap only the victim
[client1_steady]
memory.max = 1G

# Case 5 — cap only the aggressor
[client2_noisy]
memory.max = 1G
```

> **Strict one-at-a-time note:** Case 4 changes *two* knobs (B's `file_size` →
> 48G **and** the shared cap → 512M). If you want each step to isolate a single
> variable, split it into 4a (file size only) and 4b (add the 512M cap), and run
> them in sequence. Record which knob moved in each run so the p99 / refault
> delta is unambiguously attributable.

Use `-o <dir>` to send each case to its own results directory (e.g.
`-o results/case3_shared`) so `benchmark_analysis.py` can compare them
side by side.

### Analyze Results
```bash
# Analyze fairness results
./benchmark_analysis.py results/*
```

## 📈 Understanding Results

### What to look for

The primary signal is **Tenant A's p99 read latency**, compared across
conditions and across B variants:

- **A alone** (`client1_steady`) → p99 flat, near cache-hit latency.
- **A + B (`randread` / sequential `read`)** → p99 rises from eviction/re-faults (Mechanism 1).
- **A + B (`randwrite`)** → p99 rises **further** at the same eviction rate,
  the extra delta attributable to writeback queue contention (Mechanism 2).
- **A + B under cgroup `memory.low`** (uncomment in `cgroup_isolated.ini`) → partial recovery for the reader B case;
  **residual** elevation for the writer B case = the "existing tools insufficient"
  result.

### Working-set refault deltas (page-cache eviction churn)

`benchmark_analysis.py` now reports per-phase `workingset_refault_file_delta`
per cgroup, read from `memstat/`. This counts file-backed pages a tenant evicted
and had to re-fault from disk during a phase — a direct measure of how much one
tenant's activity churns another's cache.

## 🔍 Key Metrics

- **p99 / p999 read latency (μs)** — the objective; from fio `clat_ns.percentile`.
  *Lower and flatter under interference = better isolation.*
- **`workingset_refault_file_delta`** — pages re-faulted per phase per cgroup
  (page-cache eviction churn); from `memstat/` (× 4 KiB ≈ bytes re-read).
- **`pgfault_delta` / `pgmajfault_delta`** — cgroup `memory.stat` minor/major
  page faults accrued per phase; from `memstat/`.
- **PSI (`some`/`full`, memory + io)** — per-cgroup stall time; from `psi/`.
- **iostat read vs. write latency & queue depth** — surfaces writeback contention.
- **IOPS / BW** — secondary throughput context, not the objective.
- `/proc/vmstat` `nr_dirty` / `nr_writeback` and per-cgroup `file_dirty` at 1s intervals.

## ⚙️ Configuration

Edit `fairness_configs.ini` to modify per-phase parameters:
- `runtime` (seconds), `block_size`, `numjobs`, `iodepth`, `rate_iops`
- `pattern` — `randread` (victim), `read` (clean scan), `randwrite` / `write`
  (dirty B), `randrw` (mixed)
- `file_size` — choose **relative to `memory.max`** (e.g. 0.5× cap for the
  victim's hot set, 2–4× cap for B), not a fixed absolute

Multi-phase configuration format (phase-prefixed keys; matches checked-in defaults):
```ini
[client1_steady]
description = Isolated victim baseline: read 1G once/phase then idle (no aggressor)
file_size = 1G

phase_0_pattern = read
phase_0_block_size = 4k
phase_0_io_size = 1G
phase_0_rate_iops = 50000
phase_0_iodepth = 1
phase_0_numjobs = 1
phase_0_runtime = 30
phase_0_ioengine = libaio

phase_1_pattern = randread
phase_1_block_size = 4k
phase_1_io_size = 1G
phase_1_rate_iops = 50000
phase_1_iodepth = 1
phase_1_numjobs = 1
phase_1_runtime = 30
phase_1_ioengine = libaio

phase_2_pattern = randread
phase_2_block_size = 4k
phase_2_io_size = 1G
phase_2_rate_iops = 50000
phase_2_iodepth = 1
phase_2_numjobs = 1
phase_2_runtime = 30
phase_2_ioengine = libaio

[client2_noisy]
description = Isolated aggressor baseline: stream 8G, ramp bandwidth 1k -> 50k -> 1k
file_size = 8G

phase_0_pattern = read
phase_0_block_size = 4k
phase_0_rate_iops = 1024
phase_0_iodepth = 1
phase_0_numjobs = 1
phase_0_runtime = 30
phase_0_ioengine = libaio

phase_1_pattern = read
phase_1_block_size = 4k
phase_1_rate_iops = 50000
phase_1_iodepth = 32
phase_1_numjobs = 4
phase_1_runtime = 30
phase_1_ioengine = libaio

phase_2_pattern = read
phase_2_block_size = 4k
phase_2_rate_iops = 1024
phase_2_iodepth = 1
phase_2_numjobs = 1
phase_2_runtime = 30
phase_2_ioengine = libaio
```

> **Reminder:** run writer-B pairings with `-m cached`. In `direct` mode fio
> bypasses the page cache, so B produces no dirty pages and Mechanism 2 vanishes.

## 📋 Test Results

Results are saved under `results/`:
- **JSON**: `*.json` — raw fio output per phase (includes `clat_ns.percentile.99`)
- **Summary**: `summary.txt` — run summary
- **iostat**: `iostat/*.iostat` — device read/write latency & queue depth
- **PSI**: `psi/*.csv` — per-cgroup memory + io pressure time series
- **memstat**: `memstat/<client>_<mode>.csv` — per-cgroup `memory.stat` snapshots
  (`before`/`after` each phase) plus `workingset_refault_file_delta` and
  `pgfault_delta` / `pgmajfault_delta` columns

## 🛠 Troubleshooting

### Permission Issues
```bash
# sudo is required for cache clearing (drop_caches) and cgroup setup
sudo ./benchmark -m cached dual
```

### Disk Space
```bash
# B files are sized relative to the cache cap (2–4× memory.max).
# Ensure room for the largest test file plus the victim's file.
df -h .
```

### Dependencies
```bash
# Check if tools are installed
which fio gcc make iostat

# Build the benchmark
make
```

### cgroup pre-flight check
```bash
# Validate cgroup v2 before running experiments (Linux only)
sudo ./check_cgroups.sh --cgroup-config cgroup_shared.ini
```

## 🎯 What This Benchmark Aims to Show

1. A latency-sensitive reader's **p99 spikes** when it shares the page cache
   with a noisy neighbor — even at equal `io.weight` / `cpu.weight`.
2. A **buffered writer** neighbor inflates that p99 **more** than a clean
   scanner at the same eviction rate — the dirty-writeback component.
3. Standard cgroup memory isolation (`memory.low`) **partially** recovers the
   reader-neighbor case but leaves **residual** p99 elevation for the writer
   case — motivating cross-layer (memory ↔ I/O) coordination.

## 🏗️ Build and Development

### Building from Source
```bash
# Clone the repository
git clone <repository-url>
cd pagecache

# Install dependencies (see prerequisites above)
brew install fio gcc make  # macOS
# OR
sudo apt-get install fio gcc make sysstat # Linux

# Build the benchmark
make

# Clean build artifacts
make clean
```

### Available Make Targets
- `make` or `make all`: Build the benchmark
- `make clean`: Remove build artifacts
- `make setup-files`: Create dense `test_file_1G` / `test_file_8G` (once)
- `make test`: Run a single workload test
- `make run-all`: Run all workloads (`./benchmark all`)
- `make analyze`: Analyze existing results
- `make workflow`: Build, ensure files, dual run, analyze

## 🔧 Advanced Usage

### Custom Configuration
Create or modify `fairness_configs.ini`. For dual-client experiments the two
sections must be named `client1_steady` (Tenant A) and `client2_noisy`
(Tenant B); use phase-prefixed keys for multi-phase runs:
```ini
[client2_noisy]
description = Custom B: mixed random read/write neighbor
file_size = 8G                    ; ~4× the 2G cgroup cap
phase_0_pattern = randrw
phase_0_block_size = 4k
phase_0_rate_iops = 20000
phase_0_numjobs = 4
phase_0_iodepth = 32
phase_0_runtime = 120
phase_0_ioengine = libaio
```

> **Platform note:** cgroups, PSI, and `memory.stat` require **Linux (cgroup v2)**.
> The dual-client interference experiments must run on a Linux host; macOS is
> only useful for building/iterating on the code.

### Command Line Options
```bash
./benchmark --help      # Show help
./benchmark -v all      # Verbose mode
./benchmark -c custom.ini -o results/ workload_name
```

## Repository Status

The benchmark harness is **implemented and runnable on Linux (cgroup v2)**. Experiments are driven by `./benchmark`; operational details and Cases 1–6.

### Layout

| Path | Role |
|------|------|
| `benchmark.c` | Harness: INI parsing, cgroup setup, fio orchestration, telemetry sampler |
| `Makefile` | `make` → `./benchmark` (`gcc -std=c11`) |
| `fairness_configs.ini` | Workload definitions (victim, noisy neighbor, B variants) |
| `cgroup_isolated.ini` | Per-tenant cgroups; optional `memory.low` (commented out by default) |
| `cgroup_shared.ini` | Shared 2G parent pool; nested tenant cgroups |
| `check_cgroups.sh` | Pre-flight cgroup v2 validation (mirrors harness cgroup setup) |
| `setup_test_files.sh` | One-time dense `test_file_1G` / `test_file_8G` (`make setup-files`) |
| `benchmark_analysis.py` | Summarize fio p99, refault deltas, dirty/vmstat peaks, PSI |
| `results/` | Default output directory (`-o` overrides) |

### Harness

- **CLI:** `--config`, `--cgroup-config`, `-o`, `-m cached|direct|both`, `--no-cgroup`, `--no-psi`, `--drop-once`, `-v`
- **Modes:** `dual` (`client1_steady` + `client2_noisy`), single workload name, `all`
- **Cache:** `drop_caches()` before each cached phase by default; fio `direct=0` (cached) or `direct=1` (bypass). Pass `--drop-once` to drop only before phase 0 and let the cache persist across later phases — needed for multi-phase eviction stories where B's reads must accumulate to evict A's pages over time.
- **Test files:** size-tagged dense files (`test_file_1G`, `test_file_8G`) via `./setup_test_files.sh` or lazy fill in the harness; reused across experiments
- **Concurrency:** all clients in a phase forked together; phases run sequentially
- **fio output:** one JSON per client per phase (`*_pN.json`) with `clat_ns.percentile` (p99/p999)

### cgroups

- Create cgroup tree under `/sys/fs/cgroup`, enable `memory` + `io` controllers
- Apply `memory.max`, `memory.low`, `io.weight` from cgroup INI
- Attach fio via `cgroup.procs` before exec
- Per-phase `memory.stat` snapshots (`workingset_refault_file` before/after → delta in `memstat/`)

### Telemetry (1 Hz during each mode run)

- **iostat:** `iostat -dx 1` → `iostat/run_<mode>.iostat`
- **PSI:** per-cgroup `memory.pressure` + `io.pressure` → `psi/<cgroup>_<mode>.csv`
- **vmstat:** `nr_dirty`, `nr_writeback`, `pgpgin`, `pgscan_kswapd` → `dirty/vmstat_<mode>.csv`
- **Per-cgroup dirty:** `file_dirty`, `file_writeback` → `dirty/<cgroup>_<mode>_dirty.csv`

Requires `--cgroup-config` for per-tenant memstat/PSI/dirty (not recorded with `--no-cgroup`).

### Workloads (`fairness_configs.ini`)

| Section | Role |
|---------|------|
| `client1_steady` | Tenant A — rate-limited sequential `read`; victim in `dual`; run alone for Case 1a |
| `client2_noisy` | Tenant B — default `randread` (Mechanism 1); noisy neighbor in `dual`; edit `phase_0_*` for Mechanism 1 vs 2; run alone for Case 1b |

Phase keys: `pattern`, `block_size`, `iodepth`, `numjobs`, `rate_iops`, `runtime`, `ioengine`, `rwmixread`, `random_distribution` (e.g. `zipf:1.2`), `fdatasync`, `fsync`.

### Quick start

```bash
make
sudo ./check_cgroups.sh --cgroup-config cgroup_shared.ini
sudo ./benchmark --cgroup-config cgroup_shared.ini -o results/shared -m cached dual
./benchmark_analysis.py results/shared
```