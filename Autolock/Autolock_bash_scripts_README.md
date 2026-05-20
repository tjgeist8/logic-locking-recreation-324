# AutoLock Bash Scripts README

## Overview

`run_netlist_autolock.sh` and `run_RTL_autolock.sh` are convenience scripts that automate the full AutoLock flow — locking a circuit file and then testing it against a SAT attack — in a single command.

---

## Requirements

**Both scripts must be placed inside the `AutoLock` directory to work.** They depend on the other scripts and binaries in that directory (`Netlist_AutoLock.py`, `RTL_AutoLock.py`, `sld`, `yosys`, etc.) and will fail if run from anywhere else.

---

## Making the Scripts Executable

After cloning the repository, you will need to make both scripts executable before running them. From inside the `AutoLock` directory, run:

```bash
chmod +x run_netlist_autolock.sh run_RTL_autolock.sh
```

This only needs to be done once after cloning.

---

## Changing Parameters (Key Length, Population Size, etc.)

The key length is set to **64 bits by default**. If you would like to change the key length or any other parameters (population size, generation count, mutation rate, crossover rate, attack trials, etc.), you will need to edit the relevant AutoLock Python script directly before running the bash scripts. See the **"How to edit AutoLock parameters"** section of the main README for instructions on how to do this.

---

## Usage

Both scripts take two arguments:

```
./run_netlist_autolock.sh <synthesized_netlist.v> <original_bench_file.bench>
./run_RTL_autolock.sh <rtl_file.v> <original_bench_file.bench>
```

### run_netlist_autolock.sh

Runs the full AutoLock flow on a pre-synthesized netlist. The script will:

1. Run `Netlist_AutoLock.py` on your synthesized netlist to produce a locked netlist (`best_locked_netlist.v`)
2. Convert the locked netlist to a `.bench` file (`best_locked_netlist.bench`)
3. Run the SAT attack (`sld`) against the locked `.bench` file using the original `.bench` file

**Example using the included c432 test file:**
```bash
./run_netlist_autolock.sh c432_basic_gates_syn.v c432.bench
```

---

### run_RTL_autolock.sh

Runs the full AutoLock flow on an RTL Verilog file. The script will:

1. Run `RTL_AutoLock.py` on your RTL Verilog file to produce a locked RTL file (`best_locked_verilog.v`)
2. Synthesize the locked RTL file using Yosys (`synthesis_basic_gates.ys`)
3. Convert the synthesized locked file to a `.bench` file (`locked_verilog_basic_gates_syn.bench`)
4. Run the SAT attack (`sld`) against the locked `.bench` file using the original `.bench` file

**Example using the included c432 test file:**
```bash
./run_RTL_autolock.sh c432.v c432.bench
```

> **Note:** If you are using your own RTL file (not c432), you will need to update `synthesis_basic_gates.ys` with the correct top module name before running this script, as described in the main README.

---

## Output

Each step prints a header and a completion message to the terminal so you can track progress. If any step fails, the script will stop immediately and report the error.
