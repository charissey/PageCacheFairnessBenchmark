# Page Cache Fairness Benchmark for Bounding p99 Latency Spikes in Multi-Tenant KV Stores
Additional Benchmarks for https://github.com/SoujanyaPonnapalli/PageCache-Fairness

This project investigates and addresses performance isolation failures in the Linux OS page cache for co-located multi-tenant key-value store workloads. We focus on bounding p99 read latency spikes — a problem that existing OS mechanisms leave unsolved.

---

## Motivation and Context

[Delta Fair Sharing](https://arxiv.org/abs/2601.20030) (ArXiv '26) addresses performance isolation for RocksDB's *internal* resources (write buffer, read cache). For the **OS page cache**, the paper identifies interference as an open problem but does not provide a solution. That is the gap this project fills.

**The interference mechanism** *(hypothesis we aim to validate experimentally)*: When tenant B exceeds its fair share of page cache, it evicts tenant A's pages from the LRU. A then reads up to its fair share, encounters cache misses, and issues disk reads. If B is also write-heavy, kswapd/the flusher concurrently drains B's dirty pages to disk. A's reads land in the I/O queue *behind* B's writeback flushes. A's effective read latency = writeback drain time + disk read time — far higher than a baseline disk read alone. The dirty writeback does not bypass cache eviction; it **amplifies the per-miss penalty** on top of it.

**Why existing approaches miss this interference**: [cgroup memory limits](https://docs.kernel.org/admin-guide/cgroup-v2.html) and PSI-based tools like [Senpai](https://github.com/facebookincubator/senpai) act on total cached pages — they can reduce how much B evicts A, but even with perfect memory sizing, B's dirty page flushes still contend with A's reads at the I/O scheduler. PSI fires correctly for A's elevated stall but triggers the wrong remedy (memory limit adjustment) when the root cause is I/O queue contention from B's writeback.

## How the Linux Page Cache Works (and Why It Fails)

### Default Policy

The Linux page cache stores file-backed data in DRAM to avoid repeated disk reads. It is managed as a **two-list LRU** (inactive + active) per NUMA node, implemented in [`mm/vmscan.c`](https://elixir.bootlin.com/linux/latest/source/mm/vmscan.c):

- **Insertion:** A page read for the first time (`add_to_page_cache_lru()`) lands on the **inactive list**. On second access it is promoted to the **active list**.
- **Eviction under pressure:** `kswapd` wakes when free memory falls below a watermark, calls `shrink_lruvec()` → `shrink_page_list()`, and evicts cold pages from the tail of the inactive list.
- **Scan pollution:** A large sequential scan fills the inactive list and pushes out hot working-set pages before they can be promoted — the root cause of noisy-neighbor interference.
- **No tenant awareness:** All pages on the inactive list compete equally — no notion of per-tenant priority.

### How cgroups Are Applied Per Process

Memory cgroup (memcg) tracking is wired into the page fault and page cache insertion paths ([`mm/memcontrol.c`](https://elixir.bootlin.com/linux/latest/source/mm/memcontrol.c)):

1. **Charge on first access:** Each page is charged to the cgroup of the faulting process and retains that association until eviction.
2. **Per-cgroup LRU lists:** Each cgroup maintains its own inactive/active LRU (`mem_cgroup_lruvec()`). The global shrinker walks per-cgroup LRU vectors proportionally under memory pressure.
3. **`memory.low` / `memory.min` influence eviction priority:** `shrink_lruvec()` skips cgroups below their `memory.low` or `memory.min` thresholds — the *only* place tenant identity influences eviction order.
4. **Shared file pages:** A file-backed page is charged to the first-accessing cgroup; subsequent readers benefit without being charged.

### cgroup v2 Memory Knobs

| Knob | Description |
|---|---|
| `memory.min` | Hard memory floor: pages below this threshold are never reclaimed, even under system-wide pressure. Enforcement: the kernel skips this cgroup entirely during reclaim until no other memory is available. |
| `memory.low` | Soft memory floor: pages below this threshold are deprioritized for eviction relative to cgroups that are over their limit. Best-effort — the kernel may still reclaim under heavy global pressure. |
| `memory.high` | Soft ceiling: when usage exceeds this, the kernel throttles the cgroup's allocations and forces it into reclaim. Does not kill processes; used to apply sustained memory pressure. Also has the side effect of triggering writeback of dirty pages belonging to the cgroup. |
| `memory.max` | Hard ceiling: exceeding this triggers the OOM killer for processes in the cgroup. |

These knobs provide limit-based isolation, not fairness-based isolation. They tell the kernel how much memory each tenant *may* use, but do not control eviction ordering when two tenants both exceed their soft limits, and have no visibility into whether evictions are clean (free) or dirty (require writeback I/O).

**The dirty/clean blind spot:** All four knobs count *total* file-backed pages — clean and dirty together. `memory.stat` exposes `file_dirty` per cgroup, but there is no per-cgroup throttle on dirty page accumulation rate (only global `vm.dirty_background_ratio` / `vm.dirty_ratio`). A cgroup that accumulates many dirty pages and then flushes them generates a writeback burst that competes with other tenants' reads at the I/O scheduler — an interference path the memory controller can observe (via `file_dirty`) but cannot directly act on.

**Standard practice** ([Biriukov](https://biriukov.dev/docs/page-cache/6-cgroup-v2-and-page-cache/), [Kubernetes etcd guide](https://kubernetes.io/docs/tasks/administer-cluster/configure-upgrade-etcd/)): set `memory.low ≈ observed working set`, `memory.high ≈ 90% of container limit`, `memory.max` as hard ceiling. No universal percentages — requires monitoring actual usage.

### Dynamic / Adaptive cgroup Configuration

Rather than static limits, several systems use runtime PSI feedback:

**PSI as a feedback signal.** Linux 4.20+ exposes `/sys/fs/cgroup/<path>/memory.pressure` per cgroup. Subscribe to threshold-crossing events via `eventfd`:
```
# fire when memory stall exceeds 50ms in any 500ms window
echo "some 50000 500000" > /sys/fs/cgroup/tenant_a/memory.pressure
```

**[Senpai](https://github.com/facebookincubator/senpai) (Meta):** Monitors `memory.pressure`; lowers `memory.high` when pressure is below target (page out cold memory) and raises it when pressure rises. Deployed across millions of Meta servers; 20–32% memory savings ([TMO, ASPLOS '22](https://www.cs.cmu.edu/~dskarlat/publications/tmo_asplos22.pdf)).

**WSS estimation for `memory.low` sizing:** [Cuki (ATC '23)](https://www.usenix.org/system/files/atc23-gu.pdf) and [eBPF-based WSS estimation](https://arxiv.org/pdf/2303.05919) estimate per-cgroup working set size online, enabling automatic `memory.low` sizing.

**MRC-guided partitioning:** [mPart (ISMM '18)](https://dl.acm.org/doi/10.1145/3210563.3210571) constructs online miss-ratio curves per tenant and solves for the near-optimal allocation split.

**What adaptive tuning still cannot do.** PSI and Senpai fail in two specific ways relevant to this project:

- **PSI fires for the right symptom but triggers the wrong fix.** When B evicts A's pages and A faults them back in, A's `memory.pressure` and `io.pressure` both rise. Senpai responds by resizing memory limits. But if B's dirty page flushes are still in the I/O queue, A's reads remain delayed even after memory limits are corrected. The fix is incomplete because it does not address I/O queue contention.
- **PSI cannot attribute I/O queue delay to its source cgroup.** A's `io.pressure` rises whether its reads are delayed by its own workload or by B's dirty writes queued ahead. There is no kernel mechanism to say "X% of A's io.pressure is attributable to B's writeback." ⚠️ *Needs validation: measure A's p99 under (a) B clean-reads only, (b) B dirty-writes only — to quantify how much the dirty component adds beyond what memory resizing fixes.*

---

## Novelty

**The gap:** Delta Fair Sharing identifies OS page cache interference as an open problem — they do not implement a solution. Existing tools (cgroup limits, PSI/Senpai) can reduce how much B evicts A but cannot bound p99 because they miss the second interference component: B's dirty-page flushes inflating A's per-miss I/O penalty.

**Two-component model of p99 latency spike:**

```
A's p99 spike = A's cache miss rate x per-miss disk read latency
                              where per-miss latency = baseline_read + writeback_queue_delay(B)
```

Memory sizing tools (Senpai, cgroup limits) address only the first factor. They cannot reduce `writeback_queue_delay(B)` — that is an I/O scheduler problem, not a memory sizing problem.

**Why prior work misses the second factor:**
| System | What it controls | What it cannot address |
|---|---|---|
| `memory.low` / `memory.min` | Total page allocation per cgroup | Per-miss I/O latency inflation from concurrent writeback |
| PSI / Senpai | Memory reclaim throttling via stall feedback | I/O queue contention attribution; no per-cgroup dirty-page rate limit |
| Delta Fair Sharing | RocksDB-layer write buffer + block cache fairness | OS page cache path; dirty page flush scheduling at block layer |
| LRU / cache_ext policies | Eviction ordering by recency | Dirty/clean status not an eviction criterion; no I/O layer coordination |

## Repository Status

The benchmark infrastructure in this repo has the basic skeleton. See the TODO list below for what needs to change before experiments can produce the key results.


---

### Phase 0 — Scaffold

- [ ] Create `pagecache_bench/` with Makefile (`gcc -std=c11`), `src/*.c` layout, stub INI files, default `fairness_results/`
- [ ] **`config.c/h`** — INI parser for `PhaseConfig`: `runtime`, `pattern`, `block_size`, `iodepth`, `numjobs`, `rate_iops`, `ioengine`, **`random_distribution`** (e.g. `zipf:1.2`), **`fdatasync`** / **`fsync`**
- [ ] **`util.c/h` + `process.c/h`** — logging, timestamps, `run_system()`, fork/exec/wait, signal cleanup
- [ ] **`main.c` CLI** — `--config`, `--cgroup-config`, `-o`, `-m cached|direct|both`, `--no-cgroup`, `--no-psi`, `-v`; modes: `dual`, `single <workload>`, `all`

---

### Phase 1 — Single-client baseline

- [ ] **`cache.c/h`** — `drop_caches()`, `create_test_file()` via `fio --create_only`; check deps (`fio`, `iostat`)
- [ ] **`workload.c/h`** — `build_fio_cmd()`, `run_phases()`, `parse_fio_p99()`; wire zipf + fdatasync into fio CLI
- [ ] **`victim_alone`** — run `victim_randread_hot` alone; one JSON per phase + `summary.txt`
- [ ] **Validate:** flat p99 after warmup; `workingset_refault_file` ≈ 0

---

### Phase 2 — Dual-client + cgroups

- [ ] **`cgroup.c/h`** — create/apply/attach/teardown; read `memory.stat`; port from `cgroup_pressure_benchmark.c`
- [ ] **`cgroup_isolated.ini`** — `memory.low = WS` for victim; **no hard cap on B**
- [ ] **`cgroup_shared.ini`** — 2G parent pool (file sizes: 0.5× cap victim, 4× cap B)
- [ ] **`dual` mode** — fork victim + B, attach cgroups, multi-phase fio; **one JSON per phase** (no last-phase-only merge)
- [ ] **Validate:** A + `b_scan_clean` → A p99 spikes; refault delta rises

---

### Phase 3 — Workloads + telemetry

- [ ] **`fairness_configs.ini`** sections:
  - `victim_randread_hot`, `victim_alone`
  - `b_scan_clean`, `b_randwrite_dirty`, `b_mixed`, `b_checkpoint`, `b_wal_append`
  - `b_*_alone` (each B variant without victim)
- [ ] **`monitor.c/h`** — 1 Hz: PSI (system + per-cgroup), `memory.stat` before/after each phase, `iostat -dx 1`
- [ ] **`/proc/vmstat` poller** — `pgpgin`, `nr_dirty`, `nr_writeback`, `pgscan_kswapd` (see Key Metrics above)
- [ ] **Validate:** A + `b_randwrite_dirty` (cached) → A p99 **above** scan B at matched eviction; `nr_writeback` correlates

---

### Phase 4 — Experiment matrix

- [ ] **Cases 1–6** (one knob at a time; `-o results/caseN/` each):
  - Case 1: isolated baselines (each client alone)
  - Case 2: concurrent + `cgroup_isolated.ini`
  - Case 3: concurrent + `--no-cgroup`
  - Case 4: shared 512M cap + 48G randread B (split 4a/4b for strict single-variable)
  - Case 5: cap victim only (`client1 memory.max = 1G`)
  - Case 6: cap aggressor only (`client2 memory.max = 1G`)
- [ ] **Four isolation conditions:**
  - Baseline → `victim_alone`
  - Interference → `--no-cgroup dual`
  - cgroup v2 → `cgroup_isolated.ini dual`
  - Proposed → placeholder
- [ ] **Headline compare:** `b_scan_clean` vs `b_randwrite_dirty` at **same eviction rate**
- [ ] **Validate:** `memory.low` partially recovers scan B; writer B leaves residual p99 tail

---

### Phase 5 — Sweeps + analysis

- [ ] **`scripts/run_sweep.sh`** — sweep B `rate_iops` (1k / 5k / 20k / 50k / unlimited) for scan vs write → Fig 1 CSV
- [ ] **Extend `quick_fairness_analysis.py`** — all phases preserved, SLO violation rate (>2× baseline p99), side-by-side case dirs, vmstat/`file_dirty` if logged

---

### Phase 6 — Tests + docs

- [ ] **`tests/test_config_parse.c`** — INI parsing unit test
- [ ] **`tests/test_cgroup_roundtrip.sh`** — create → set `memory.low` → attach → read → destroy
- [ ] Update this file: C build (`gcc` not `g++`), new binary name `pagecache_bench`

---

### Build-order checklist (learning path)

| Step | Milestone | Pass criteria |
|------|-----------|---------------|
| 1 | `victim_alone` | Flat p99; refault ≈ 0 after warmup |
| 2 | `dual` + `b_scan_clean` | A p99 spikes; refault delta rises |
| 3 | `dual` + `b_randwrite_dirty` | A p99 > scan at same eviction; `nr_writeback` up |
| 4 | `cgroup_isolated.ini` | Scan largely recovers; writer residual tail |
| 5 | Cases 1–6 + sweep | Full workflow; Fig 1 curves diverge |