# Page-Cache Fairness Analysis — results/client1 - Client1 only, randread

## 📈 READ LATENCY (Tenant A objective)
  client1_steady_cached_p0.json [client1_steady_p0]: p99=2.5us p999=16.1us iops=6813 bw=26.6MiB/s

  client1_steady_cached_p1.json [client1_steady_p1]: p99=2.4us p999=16.1us iops=6879 bw=26.9MiB/s

  client1_steady_cached_p2.json [client1_steady_p2]: p99=2.4us p999=16.3us iops=6887 bw=26.9MiB/s

## 🔁 WORKING SET REFAULTS (page-cache eviction churn)


**client1_steady_cached:**
  phase 0: delta            0 pages (     0.0 MiB)  |  total            0 pages (     0.0 MiB)

  phase 1: delta            0 pages (     0.0 MiB)  |  total            0 pages (     0.0 MiB)

  phase 2: delta            0 pages (     0.0 MiB)  |  total            0 pages (     0.0 MiB)

## 💾 MEMORY CONSUMPTION (cgroup memory.current + page faults)


**client1_steady_cached:**
  phase 0 (before):       0.0 MiB

  phase 0 (after):     824.7 MiB  |  pgfault_delta=4,489  pgmajfault_delta=180

  phase 1 (before):     824.7 MiB

  phase 1 (after):     832.6 MiB  |  pgfault_delta=4,127  pgmajfault_delta=0

  phase 2 (before):     832.6 MiB

  phase 2 (after):     833.7 MiB  |  pgfault_delta=4,125  pgmajfault_delta=0

## 🎯 CACHE HIT / MISS (fio logical reads vs. device reads)

  Approximate: miss ≈ device reads seen in iostat during the phase
  window; hit = fio's logical reads minus that. iostat samples are
  bucketed by report index, not exact timestamp — treat as an
  estimate, not an exact count.

**client1_steady_cached:**
  phase 0: logical_reads=204,411  hit=0 (0.00%)  miss≈204,411 (100.00%)

  phase 1: logical_reads=206,385  hit=0 (0.00%)  miss≈206,385 (100.00%)

  phase 2: logical_reads=206,613  hit=0 (0.00%)  miss≈206,613 (100.00%)

## 💧 DIRTY-PAGE PRESSURE (vmstat + per-cgroup file_dirty)

  client1_steady_cached_dirty: file_dirty peak=12,288  file_writeback peak=0

  vmstat_cached: nr_dirty peak=93  nr_writeback peak=4  pgpgin peak=176,314,220  pgscan_kswapd peak=0

## 🚦 PSI PRESSURE (memory + io 'some' stall over run)

  client1_steady_cached: memory=0.0ms  io=77053.5ms

# Page-Cache Fairness Analysis — results/client2 - Client2 only, Sequential
## 📈 READ LATENCY (Tenant A objective)

  client2_noisy_cached_p0.json [client2_noisy_p0]: p99=4.8us p999=16.2us iops=1024 bw=4.0MiB/s

  client2_noisy_cached_p1.json [client2_noisy_p1]: p99=2572.3us p999=3784.7us iops=179103 bw=699.6MiB/s

  client2_noisy_cached_p2.json [client2_noisy_p2]: p99=4.4us p999=19.8us iops=1024 bw=4.0MiB/s

## 🔁 WORKING SET REFAULTS (page-cache eviction churn)


**client2_noisy_cached:**
  phase 0: delta            0 pages (     0.0 MiB)  |  total            0 pages (     0.0 MiB)

  phase 1: delta          704 pages (     2.8 MiB)  |  total          704 pages (     2.8 MiB)

  phase 2: delta          692 pages (     2.7 MiB)  |  total        1,396 pages (     5.5 MiB)

## 💾 MEMORY CONSUMPTION (cgroup memory.current + page faults)


**client2_noisy_cached:**
  phase 0 (before):       0.0 MiB

  phase 0 (after):     144.1 MiB  |  pgfault_delta=4,477  pgmajfault_delta=180

  phase 1 (before):     144.1 MiB

  phase 1 (after):    2040.2 MiB  |  pgfault_delta=4,718  pgmajfault_delta=35

  phase 2 (before):    2040.2 MiB

  phase 2 (after):     146.3 MiB  |  pgfault_delta=4,187  pgmajfault_delta=41

## 🎯 CACHE HIT / MISS (fio logical reads vs. device reads)

  Approximate: miss ≈ device reads seen in iostat during the phase
  window; hit = fio's logical reads minus that. iostat samples are
  bucketed by report index, not exact timestamp — treat as an
  estimate, not an exact count.

**client2_noisy_cached:**
  phase 0: logical_reads=30,720  hit=29,599 (96.35%)  miss≈1,121 (3.65%)

  phase 1: logical_reads=5,373,452  hit=5,329,644 (99.18%)  miss≈43,808 (0.82%)

  phase 2: logical_reads=30,720  hit=27,638 (89.97%)  miss≈3,082 (10.03%)

## 💧 DIRTY-PAGE PRESSURE (vmstat + per-cgroup file_dirty)

  client2_noisy_cached_dirty: file_dirty peak=20,480  file_writeback peak=0
  vmstat_cached: nr_dirty peak=116  nr_writeback peak=7  pgpgin peak=173,808,060  pgscan_kswapd peak=0

## 🚦 PSI PRESSURE (memory + io 'some' stall over run)

  client2_noisy_cached: memory=175.4ms  io=21076.0ms


# Page-Cache Fairness Analysis — results/cached_dual - Phase0 Client 1 Seq
## 📈 READ LATENCY (Tenant A objective)

  client1_steady_cached_p0.json [client1_steady_p0]: p99=5.3us p999=5.7us iops=47182 bw=184.3MiB/s

  client1_steady_cached_p1.json [client1_steady_p1]: p99=17.0us p999=20.4us iops=1582 bw=6.2MiB/s

  client1_steady_cached_p2.json [client1_steady_p2]: p99=2.4us p999=17.0us iops=6823 bw=26.7MiB/s

  client2_noisy_cached_p0.json [client2_noisy_p0]: p99=4.4us p999=16.3us iops=1024 bw=4.0MiB/s

  client2_noisy_cached_p1.json [client2_noisy_p1]: p99=2039.8us p999=2375.7us iops=197206 bw=770.3MiB/s

  client2_noisy_cached_p2.json [client2_noisy_p2]: p99=3.9us p999=17.5us iops=1024 bw=4.0MiB/s

## 🔁 WORKING SET REFAULTS (page-cache eviction churn)


**client1_steady_cached:**
  phase 0: delta            0 pages (     0.0 MiB)  |  total            0 pages (     0.0 MiB)

  phase 1: delta            0 pages (     0.0 MiB)  |  total            0 pages (     0.0 MiB)

  phase 2: delta          348 pages (     1.4 MiB)  |  total          348 pages (     1.4 MiB)

**client2_noisy_cached:**
  phase 0: delta            0 pages (     0.0 MiB)  |  total            0 pages (     0.0 MiB)

  phase 1: delta            0 pages (     0.0 MiB)  |  total            0 pages (     0.0 MiB)

  phase 2: delta          468 pages (     1.8 MiB)  |  total          468 pages (     1.8 MiB)

## 💾 MEMORY CONSUMPTION (cgroup memory.current + page faults)


**client1_steady_cached:**
  phase 0 (before):       0.0 MiB

  phase 0 (after):    1039.2 MiB  |  pgfault_delta=4,451  pgmajfault_delta=141

  phase 1 (before):    1039.2 MiB

  phase 1 (after):      43.9 MiB  |  pgfault_delta=4,133  pgmajfault_delta=0

  phase 2 (before):      43.9 MiB

  phase 2 (after):     813.0 MiB  |  pgfault_delta=4,221  pgmajfault_delta=44

**client2_noisy_cached:**
  phase 0 (before):       0.0 MiB

  phase 0 (after):     131.8 MiB  |  pgfault_delta=4,444  pgmajfault_delta=135

  phase 1 (before):     131.8 MiB

  phase 1 (after):    1984.3 MiB  |  pgfault_delta=4,700  pgmajfault_delta=0

  phase 2 (before):    1984.3 MiB

  phase 2 (after):     136.2 MiB  |  pgfault_delta=4,206  pgmajfault_delta=47

## 🎯 CACHE HIT / MISS (fio logical reads vs. device reads)

  Approximate: miss ≈ device reads seen in iostat during the phase
  window; hit = fio's logical reads minus that. iostat samples are
  bucketed by report index, not exact timestamp — treat as an
  estimate, not an exact count.

**client1_steady_cached:**
  phase 0: logical_reads=262,144  hit=256,331 (97.78%)  miss≈5,813 (2.22%)

  phase 1: logical_reads=47,452  hit=0 (0.00%)  miss≈47,452 (100.00%)

  phase 2: logical_reads=204,683  hit=0 (0.00%)  miss≈204,683 (100.00%)

**client2_noisy_cached:**
  phase 0: logical_reads=30,720  hit=24,907 (81.08%)  miss≈5,813 (18.92%)

  phase 1: logical_reads=5,916,372  hit=5,821,525 (98.40%)  miss≈94,847 (1.60%)

  phase 2: logical_reads=30,720  hit=0 (0.00%)  miss≈30,720 (100.00%)

## 💧 DIRTY-PAGE PRESSURE (vmstat + per-cgroup file_dirty)

  clients_client1_steady_cached_dirty: file_dirty peak=16,384  file_writeback peak=0

  clients_client2_noisy_cached_dirty: file_dirty peak=0  file_writeback peak=0

  vmstat_cached: nr_dirty peak=98  nr_writeback peak=34  pgpgin peak=160,515,572  pgscan_kswapd peak=0

## 🚦 PSI PRESSURE (memory + io 'some' stall over run)

  clients_client1_steady_cached: memory=58.1ms  io=53302.5ms

  clients_client2_noisy_cached: memory=195.3ms  io=19638.2ms




# Page-Cache Fairness Analysis — results/cached_dual - All rand read
## 📈 READ LATENCY (Tenant A objective)

  client1_steady_cached_p0.json [client1_steady_p0]: p99=2.4us p999=15.8us iops=6681 bw=26.1MiB/s

  client1_steady_cached_p1.json [client1_steady_p1]: p99=17.0us p999=21.1us iops=1590 bw=6.2MiB/s

  client1_steady_cached_p2.json [client1_steady_p2]: p99=2.5us p999=15.9us iops=6769 bw=26.4MiB/s

  client2_noisy_cached_p0.json [client2_noisy_p0]: p99=4.6us p999=15.4us iops=1024 bw=4.0MiB/s

  client2_noisy_cached_p1.json [client2_noisy_p1]: p99=2089.0us p999=2441.2us iops=190352 bw=743.6MiB/s

  client2_noisy_cached_p2.json [client2_noisy_p2]: p99=9.2us p999=17.5us iops=1024 bw=4.0MiB/s

## 🔁 WORKING SET REFAULTS (page-cache eviction churn)


**client1_steady_cached:**
  phase 0: delta            0 pages (     0.0 MiB)  |  total            0 pages (     0.0 MiB)

  phase 1: delta            0 pages (     0.0 MiB)  |  total            0 pages (     0.0 MiB)

  phase 2: delta          484 pages (     1.9 MiB)  |  total          484 pages (     1.9 MiB)

**client2_noisy_cached:**
  phase 0: delta            0 pages (     0.0 MiB)  |  total            0 pages (     0.0 MiB)

  phase 1: delta            0 pages (     0.0 MiB)  |  total            0 pages (     0.0 MiB)

  phase 2: delta          327 pages (     1.3 MiB)  |  total          327 pages (     1.3 MiB)

## 💾 MEMORY CONSUMPTION (cgroup memory.current + page faults)


**client1_steady_cached:**
  phase 0 (before):       0.0 MiB

  phase 0 (after):     797.5 MiB  |  pgfault_delta=4,485  pgmajfault_delta=144

  phase 1 (before):     797.5 MiB

  phase 1 (after):      43.0 MiB  |  pgfault_delta=4,144  pgmajfault_delta=0

  phase 2 (before):      43.0 MiB

  phase 2 (after):     806.4 MiB  |  pgfault_delta=4,200  pgmajfault_delta=52

**client2_noisy_cached:**
  phase 0 (before):       0.0 MiB

  phase 0 (after):     132.8 MiB  |  pgfault_delta=4,455  pgmajfault_delta=149

  phase 1 (before):     132.8 MiB

  phase 1 (after):    1985.0 MiB  |  pgfault_delta=4,687  pgmajfault_delta=0

  phase 2 (before):    1985.0 MiB

  phase 2 (after):     136.2 MiB  |  pgfault_delta=4,207  pgmajfault_delta=47

## 🎯 CACHE HIT / MISS (fio logical reads vs. device reads)

  Approximate: miss ≈ device reads seen in iostat during the phase
  window; hit = fio's logical reads minus that. iostat samples are
  bucketed by report index, not exact timestamp — treat as an
  estimate, not an exact count.

**client1_steady_cached:**
  phase 0: logical_reads=200,441  hit=0 (0.00%)  miss≈200,441 (100.00%)

  phase 1: logical_reads=47,693  hit=0 (0.00%)  miss≈47,693 (100.00%)

  phase 2: logical_reads=203,079  hit=0 (0.00%)  miss≈203,079 (100.00%)

**client2_noisy_cached:**
  phase 0: logical_reads=30,720  hit=0 (0.00%)  miss≈30,720 (100.00%)

  phase 1: logical_reads=5,710,749  hit=5,607,861 (98.20%)  miss≈102,888 (1.80%)

  phase 2: logical_reads=30,721  hit=0 (0.00%)  miss≈30,721 (100.00%)

## 💧 DIRTY-PAGE PRESSURE (vmstat + per-cgroup file_dirty)

  clients_client1_steady_cached_dirty: file_dirty peak=16,384  file_writeback peak=0

  clients_client2_noisy_cached_dirty: file_dirty peak=24,576  file_writeback peak=0

  vmstat_cached: nr_dirty peak=88  nr_writeback peak=9  pgpgin peak=152,251,388  pgscan_kswapd peak=0

## 🚦 PSI PRESSURE (memory + io 'some' stall over run)

  clients_client1_steady_cached: memory=67.1ms  io=76299.7ms

  clients_client2_noisy_cached: memory=210.4ms  io=20299.9ms