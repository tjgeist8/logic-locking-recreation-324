#!/bin/bash

# run_netlist_autolock.sh
# Runs the full AutoLock flow on a synthesized netlist file.
# Usage: ./run_netlist_autolock.sh <synthesized_netlist.v> <original_bench_file.bench>

set -e

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <synthesized_netlist.v> <original_bench_file.bench>"
    exit 1
fi

NETLIST="$1"
ORIGINAL_BENCH="$2"

echo "============================================"
echo " Step 1: Running AutoLock on netlist..."
echo "============================================"
python3 Netlist_AutoLock.py "$NETLIST"
wait
echo "AutoLock complete. Output: best_locked_netlist.v"

echo ""
echo "============================================"
echo " Step 2: Converting locked netlist to .bench..."
echo "============================================"
python3 locked_netlist_to_bench.py --input best_locked_netlist.v --output best_locked_netlist.bench
wait
echo "Conversion complete. Output: best_locked_netlist.bench"

echo ""
echo "============================================"
echo " Step 3: Running SAT attack..."
echo "============================================"
./sld best_locked_netlist.bench "$ORIGINAL_BENCH"
wait
echo "SAT attack complete."

echo ""
echo "============================================"
echo " All steps finished successfully."
echo "============================================"
