# Pagecache Fairness Benchmark — Linux image with fio + cgroup tooling.
# Run with --privileged --cgroupns=host so the harness can create cgroups
# and drop caches (see README "Running with Docker").
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        fio \
        sysstat \
        python3 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /bench

COPY Makefile benchmark.c fairness_configs.ini \
     cgroup_shared.ini cgroup_isolated.ini \
     setup_test_files.sh check_cgroups.sh \
     benchmark_analysis.py ./

RUN make && chmod +x setup_test_files.sh check_cgroups.sh benchmark_analysis.py

# Test files and results are expected via bind mounts (see README).
# Do not bake multi-GB test_file_* into the image.

CMD ["./benchmark", "-h"]
