#!/bin/bash

# run_RTL_autolock.sh
# Runs the full AutoLock flow on an RTL Verilog file.
# Usage: ./run_RTL_autolock.sh <rtl_file.v> <original_bench_file.bench>

set -e

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <rtl_file.v> <original_bench_file.bench>"
    exit 1
fi

RTL_FILE="$1"
ORIGINAL_BENCH="$2"

echo "============================================"
echo " Step 1: Running AutoLock on RTL Verilog..."
echo "============================================"
python3 RTL_AutoLock.py "$RTL_FILE"
wait
echo "AutoLock complete. Output: best_locked_verilog.v"

echo ""
echo "============================================"
echo " Step 2: Synthesizing locked RTL with Yosys..."
echo "============================================"
yosys synthesis_basic_gates.ys
wait
echo "Synthesis complete. Output: locked_verilog_basic_gates_syn.v"

echo ""
echo "============================================"
echo " Step 3: Converting synthesized RTL to .bench..."
echo "============================================"
python3 locked_verilog_to_bench.py --input locked_verilog_basic_gates_syn.v --output locked_verilog_basic_gates_syn.bench
wait
echo "Conversion complete. Output: locked_verilog_basic_gates_syn.bench"

echo ""
echo "============================================"
echo " Step 4: Running SAT attack..."
echo "============================================"
./sld locked_verilog_basic_gates_syn.bench "$ORIGINAL_BENCH"
wait
echo "SAT attack complete."

echo ""
echo "============================================"
echo " All steps finished successfully."
echo "============================================"
