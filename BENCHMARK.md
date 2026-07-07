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
├── cgroup_isolated.ini            # Isolated / memory.low cgroup layout
├── benchmark.c                    # C benchmark implementation
├── benchmark                      # Compiled C binary
├── Makefile                       # Build configuration
├── benchmark_analysis.py          # Results analysis (fio + PSI + refaults)
├── benchmark_results/             # Test results directory
│   ├── *.json                     # Raw fio output (per phase)
│   ├── iostat/                    # iostat -x logs
│   ├── psi/                       # Per-cgroup PSI time series (CSV)
│   └── memstat/                   # Per-cgroup memory.stat snapshots (CSV)
├── test_file_*                    # Generated test files (size-tagged)
└── README.md                      # Research thesis and experiment plan
```

## Gettings Started

### Prerequisites
- `fio` (I/O benchmark tool)
- `gcc` with C11 support
- `make` (build tool)
- `iostat` (I/O monitoring)
- Sufficient disk space for test files (17+ GB)

### Install Dependencies (macOS)
```bash
brew install fio gcc make
```

### Install Dependencies (Ubuntu/Debian)
```bash
sudo apt-get install fio gcc make sysstat
```

### Build the Benchmark
```bash
make
```

## 📊 Workload Design

Workloads are grouped by the **role** they play in an experiment, not by a
read/write × iodepth grid. Sizes are expressed **relative to the cgroup memory
cap** (`memory.max`, 2G in `cgroup_shared.ini`) rather than as fixed absolutes,
because interference depends on working-set-to-cache ratio.

### Tenant A — the victim (what we measure)

| Workload | Working set | Pattern | Distribution | Concurrency | Mode | Rationale |
|---|---|---|---|---|---|---|
| `victim_randread_hot` | 0.5× cap (fits) | randread, 4k | `zipf:1.2` | numjobs=4, iodepth=1, **rate-limited** | cached | Latency-sensitive reader whose hot set fits in cache; report clat **p99**. Rate limit keeps p99 an SLO signal, not a saturation artifact. |

### Tenant B — the noisy neighbor (isolates the mechanisms)

| Workload | File | Pattern | bs | Mode | Mechanism |
|---|---|---|---|---|---|
| `b_scan_clean` | 4× cap | read (sequential) | **1M** | cached | **1** — LRU pollution / eviction, no writeback |
| `b_randwrite_dirty` | 4× cap | randwrite | 4k | **cached (buffered)** | **2** — eviction **+** dirty writeback contention |
| `b_mixed` | 4× cap | randrw (`rwmixread=50`) | 4k | cached | **1 + 2** combined |
| `b_checkpoint` | 2× cap | write + `fdatasync=1000` | 1M | cached | Periodic flush **bursts** (PostgreSQL checkpoint / etcd commit) |
| `b_wal_append` | 2× cap | write (sequential) + `fdatasync=32` | 4k | cached | Append-only log dirtying (bbolt/etcd WAL) |

### Baselines (required to compute the interference delta)

| Workload | Setup | Purpose |
|---|---|---|
| `victim_alone` | A only, no B | Flat-p99 reference; interference = (A+B) − this |
| `b_*_alone` | each B only | Confirm B is not self-throttled |

## 🔬 Experiment Structure

The unit of experiment is a **dual-client pairing** (`dual` mode), run under the
four isolation conditions from the thesis:

| Condition | Setup | Expected outcome |
|---|---|---|
| Baseline | A alone (`victim_alone`) | p99 flat; cache-hit ≈ 100% |
| Interference | A + B, no isolation | A's p99 spikes; writer B worse than reader B at equal eviction |
| cgroup v2 | A's `memory.low` = WS, no hard cap on B (`cgroup_isolated.ini`) | Partial recovery; residual p99 elevation under writer B |
| Proposed policy | A + B under proposed policy | A's p99 within SLO for both B variants |

**Key comparison:** `victim + b_scan_clean` vs `victim + b_randwrite_dirty` at the
**same eviction rate** → does dirty writeback add p99 beyond clean eviction?

**Intensity sweep (Fig 1):** run `b_scan_clean` and `b_randwrite_dirty` across a
range of `phase_*_rate_iops` (e.g. 1k / 5k / 20k / 50k / unlimited) to plot
B's intensity (X) vs A's p99 (Y), one curve per mechanism.

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
| 2 | Isolated Clients | Concurrent | `cgroup_isolated.ini` (each client its own memory floor) | +concurrency, **with** isolation | Whether isolation keeps p99 ≈ baseline when both run together |
| 3 | Shared Sequential | Concurrent | **no memory limits** (`--no-cgroup`) | remove cgroup memory limits (shared pool) | Raw interference with nothing protecting A |
| 4 | Shared Client 2 Random Read | Concurrent | shared, parent `memory.max = 512M` | B → 48G file, `randread`, under tiny shared cap | Heavy eviction pressure: B's working set ≫ cache |
| 5 | Shared Client 1 Limited | Concurrent | shared, `client1_steady memory.max = 1G` | cap the **victim's** memory | Whether limiting A (not B) helps or hurts A's p99 |
| 6 | Shared Client 2 Limited | Concurrent | shared, `client2_noisy memory.max = 1G` | cap the **aggressor's** memory | The standard mitigation: does capping B bound A's p99? |

**How to read the progression:**
- **1 → 2:** adds concurrency but keeps isolation → expect A's p99 stays near baseline.
- **2 → 3:** removes the memory limits → expect A's p99 to spike (interference).
- **3 → 4:** makes B a cache-thrashing random reader under a 512M cap → expect
  maximal eviction of A and large `workingset_refault_file_delta` for A.
- **3 → 5** and **3 → 6:** each caps exactly one tenant → compares "limit the
  victim" vs "limit the noisy neighbor" as isolation strategies.

### Running each case

```bash
# Case 1 — Isolated Baselines (run each client on its own, no contention)
./benchmark client1_steady
./benchmark client2_noisy

# Case 2 — Isolated Clients (concurrent, isolated cgroups)
sudo ./benchmark --cgroup-config cgroup_isolated.ini -m cached dual

# Case 3 — Shared Sequential (concurrent, no memory limits)
sudo ./benchmark --no-cgroup -m cached dual

# Cases 4–6 — Shared with one cap changed (edit the cgroup .ini, then run)
sudo ./benchmark --cgroup-config cgroup_shared.ini -m cached dual
```

For Cases 4–6, change the single `memory.max` line in the cgroup config (keep
everything else identical to Case 3's shared layout):

```ini
# Case 4 — parent (shared) cap = 512M, and set client2_noisy file_size = 48G
[clients]
cgroup_name = clients
memory.max = 512M

# Case 5 — cap only the victim
[client1_steady]
memory.max = 1G

# Case 6 — cap only the aggressor
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

## 🔧 Usage

### Run a Dual-Client Interference Experiment (primary mode)

`dual` mode runs `client1_steady` (Tenant A) and `client2_noisy` (Tenant B)
concurrently under cgroups — this is the experiment that produces the p99 result.

```bash
# Run the A + B pairing in BOTH cached and direct modes
./benchmark dual

# Writer-B interference must run in CACHED mode (direct=1 disables Mechanism 2)
./benchmark -m cached dual

# With a specific cgroup layout
./benchmark --cgroup-config cgroup_shared.ini -m cached dual
```

### Run a Single Workload (characterization / baselines)

```bash
# Baseline: victim alone
./benchmark -v victim_alone

# Characterize one noisy-neighbor variant on its own
./benchmark b_randwrite_dirty
```

### Run Everything

```bash
./benchmark all        # every workload defined in the config
./benchmark -v all     # verbose
```

### Analyze Results
```bash
# Analyze fairness results
./benchmark_analysis.py benchmark_results/
```

## 📈 Understanding Results

### What to look for

The primary signal is **Tenant A's p99 read latency**, compared across
conditions and across B variants:

- **A alone** → p99 flat, near cache-hit latency.
- **A + `b_scan_clean`** → p99 rises from eviction/re-faults (Mechanism 1).
- **A + `b_randwrite_dirty`** → p99 rises **further** at the same eviction rate,
  the extra delta attributable to writeback queue contention (Mechanism 2).
- **A + B under cgroup `memory.low`** → partial recovery for the reader B case;
  **residual** elevation for the writer B case = the "existing tools insufficient"
  result.

### Working-set refault deltas (page-cache eviction churn)

`benchmark_analysis.py` now reports per-phase `workingset_refault_file_delta`
per cgroup, read from `memstat/`. This counts file-backed pages a tenant evicted
and had to re-fault from disk during a phase — a direct measure of how much one
tenant's activity churns another's cache.

```
## 🔁 WORKING SET REFAULTS (page-cache eviction churn)
==================================================
### CACHED mode

**client1_steady:**
  phase 2:          300 pages (     1.2 MiB)

**client2_noisy:**
  phase 2:       25,000 pages (    97.7 MiB)

  Refault comparison (client1_steady vs client2_noisy):
    phase 2: client1_steady=300  client2_noisy=25,000  → client2_noisy refaulted 83.3× more
```

## 🔍 Key Metrics

- **p99 / p999 read latency (μs)** — the objective; from fio `clat_ns.percentile`.
  *Lower and flatter under interference = better isolation.*
- **`workingset_refault_file_delta`** — pages re-faulted per phase per cgroup
  (page-cache eviction churn); from `memstat/` (× 4 KiB ≈ bytes re-read).
- **PSI (`some`/`full`, memory + io)** — per-cgroup stall time; from `psi/`.
- **iostat read vs. write latency & queue depth** — surfaces writeback contention.
- **IOPS / BW** — secondary throughput context, not the objective.
- *(Planned, TODO in `README.md`)* `/proc/vmstat` `nr_dirty` / `nr_writeback`
  and per-cgroup `file_dirty` at 1s intervals.

## ⚙️ Configuration

Edit `fairness_configs.ini` to modify per-phase parameters:
- `runtime` (seconds), `block_size`, `numjobs`, `iodepth`, `rate_iops`
- `pattern` — `randread` (victim), `read` (clean scan), `randwrite` / `write`
  (dirty B), `randrw` (mixed)
- `file_size` — choose **relative to `memory.max`** (e.g. 0.5× cap for the
  victim's hot set, 2–4× cap for B), not a fixed absolute

Multi-phase configuration format (phase-prefixed keys):
```ini
[client1_steady]                 ; Tenant A — the victim
description = Hot-set random reader; measure p99
file_size = 1G
phase_0_pattern = randread
phase_0_block_size = 4k
phase_0_rate_iops = 5000
phase_0_iodepth = 1
phase_0_numjobs = 4
phase_0_runtime = 60
phase_0_ioengine = libaio

[client2_noisy]                 ; Tenant B — buffered dirty writer (Mechanism 2)
description = Random writer generating dirty writeback
file_size = 8G
phase_0_pattern = randwrite
phase_0_block_size = 4k
phase_0_rate_iops = 20000
phase_0_iodepth = 32
phase_0_numjobs = 4
phase_0_runtime = 60
phase_0_ioengine = libaio
```

> **Reminder:** run writer-B pairings with `-m cached`. In `direct` mode fio
> bypasses the page cache, so B produces no dirty pages and Mechanism 2 vanishes.

**Planned fields (not yet parsed — see TODO in `README.md`):**
`phase_N_random_distribution` (e.g. `zipf:1.2`) for the victim's hot set, and
`phase_N_fdatasync` / `phase_N_fsync` (flush cadence) for the checkpoint/WAL
B variants. These require adding fields to `PhaseConfig` and the fio command
builders in `benchmark.c`.

## 📋 Test Results

Results are saved under `benchmark_results/`:
- **JSON**: `*.json` — raw fio output per phase (includes `clat_ns.percentile.99`)
- **Summary**: `summary.txt` — run summary
- **iostat**: `iostat/*.iostat` — device read/write latency & queue depth
- **PSI**: `psi/*.csv` — per-cgroup memory + io pressure time series
- **memstat**: `memstat/<client>_<mode>.csv` — per-cgroup `memory.stat` snapshots
  (`before`/`after` each phase) plus the `workingset_refault_file_delta` rows

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

## 📊 Example Complete Workflow

```bash
# 1. Build the benchmark
make

# 2. Run the A + B interference experiment in cached mode
sudo ./benchmark --cgroup-config cgroup_shared.ini -m cached dual

# 3. Analyze results (fio p99 + PSI + refault deltas)
./benchmark_analysis.py benchmark_results/

# 4. View summary
cat benchmark_results/summary.txt
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
- `make test`: Run a single workload test
- `make benchmark`: Run all benchmarks
- `make analyze`: Analyze existing results
- `make workflow`: Complete build, test, analyze workflow

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