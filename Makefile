CC      ?= gcc
CFLAGS  ?= -std=c11 -O2 -Wall -Wextra -D_GNU_SOURCE
TARGET   = benchmark
SRC      = benchmark.c

.PHONY: all clean test run-all analyze workflow

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(TARGET)

# Run a single-workload baseline
test: $(TARGET)
	./$(TARGET) -v victim_alone

# Run every workload defined in the config
run-all: $(TARGET)
	./$(TARGET) all

# Analyze existing results
analyze:
	./benchmark_analysis.py benchmark_results/

# Full build -> dual experiment -> analyze
workflow: $(TARGET)
	./$(TARGET) -m cached dual
	./benchmark_analysis.py benchmark_results/
