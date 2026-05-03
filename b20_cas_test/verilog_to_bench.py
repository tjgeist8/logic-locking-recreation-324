import re
import argparse
import sys
import subprocess

def validate_with_abc(bench_file):
    print("\n--- Validating BENCH file with ABC ---")
    try:
        # Check if we should use yosys-abc (Mac default) or standard abc
        abc_cmd = "yosys-abc"
        try:
            subprocess.run([abc_cmd, "-c", "quit"], capture_output=True, check=True)
        except FileNotFoundError:
            abc_cmd = "abc" # Fallback to standard abc if yosys-abc isn't found
            
        # Run abc with a command string: read the bench file, print stats, and quit
        cmd = [abc_cmd, "-c", f"read_bench {bench_file}; print_stats; quit"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        output = result.stdout + result.stderr
        
        # ABC usually doesn't throw a standard non-zero exit code on bad files, 
        # so we must check the text output for common failure strings.
        if "Error" in output or "failed" in output.lower() or "Cannot open" in output:
            print("❌ Validation FAILED. ABC rejected the BENCH file:")
            # Print only the relevant error lines from ABC
            for line in output.split('\n'):
                if "Error" in line or "failed" in line.lower():
                    print(f"   {line.strip()}")
        else:
            print("✅ Validation SUCCESS. ABC successfully parsed the file topology.")
            # Extract and print the ABC stats line to prove it read the gates
            for line in output.split('\n'):
                if "nd" in line and "edge" in line: # Typical markers of ABC print_stats
                    print(f"   ABC DAG Stats: {line.strip()}")

    except FileNotFoundError:
        print("⚠️ Warning: Could not find 'yosys-abc' or 'abc' in your system PATH. Skipping validation.")
    except Exception as e:
        print(f"⚠️ An error occurred during validation: {e}")


def convert_verilog_to_bench(verilog_file, bench_file, run_validation):
    try:
        with open(verilog_file, 'r') as f:
            v_code = f.read()
    except FileNotFoundError:
        print(f"Error: Could not find input file '{verilog_file}'")
        sys.exit(1)

    # 1. Clean up the Verilog string
    v_code = re.sub(r'//.*', '', v_code)
    v_code = re.sub(r'/\*.*?\*/', '', v_code, flags=re.DOTALL)
    
    v_code = re.sub(r'\bmodule\s+.*?;', '', v_code, flags=re.DOTALL)
    v_code = re.sub(r'\bwire\s+.*?;', '', v_code, flags=re.DOTALL)
    v_code = re.sub(r'\bendmodule\b', '', v_code)

    inputs = []
    outputs = []
    bench_lines = []

    # 2. Extract Primary Inputs
    for m in re.finditer(r'\binput\s+(.*?);', v_code, re.DOTALL):
        ports = [p.strip() for p in m.group(1).replace('\n', '').split(',')]
        inputs.extend(ports)

    # 3. Extract Primary Outputs
    for m in re.finditer(r'\boutput\s+(.*?);', v_code, re.DOTALL):
        ports = [p.strip() for p in m.group(1).replace('\n', '').split(',')]
        outputs.extend(ports)

    # Remove declarations
    v_code = re.sub(r'\binput\s+.*?;', '', v_code, flags=re.DOTALL)
    v_code = re.sub(r'\boutput\s+.*?;', '', v_code, flags=re.DOTALL)

    # 4. Parse Gate Instantiations
    gate_pattern = re.compile(r'\b([A-Z][A-Z0-9_]+)\s+([a-zA-Z0-9_\\\[\]]+)\s*\((.*?)\);', re.DOTALL)
    
    for match in gate_pattern.finditer(v_code):
        cell_type = match.group(1)
        pins_str = match.group(3)
        
        base_gate = cell_type.split('_')[0]
        base_gate = ''.join([i for i in base_gate if not i.isdigit()]) 
        
        if base_gate == 'INV': base_gate = 'NOT'
        if base_gate == 'BUF': base_gate = 'BUFF'
        
        pin_pattern = re.compile(r'\.\s*([A-Z0-9_]+)\s*\(\s*([a-zA-Z0-9_\\\[\]]+)\s*\)')
        pins = pin_pattern.findall(pins_str)
        
        out_nets = []
        in_nets = []
        
        for pin_name, net_name in pins:
            if pin_name in ['Z', 'ZN', 'Q', 'QN']:
                out_nets.append(net_name)
            elif pin_name not in ['CK', 'clk', 'clock']:
                in_nets.append(net_name)

        if out_nets:
            main_out = out_nets[0]
            if base_gate == 'DFF':
                 bench_lines.append(f"{main_out} = DFF({in_nets[0]})")
            else:
                 inputs_joined = ', '.join(in_nets)
                 bench_lines.append(f"{main_out} = {base_gate}({inputs_joined})")
                 
            if len(out_nets) > 1 and 'QN' in [p[0] for p in pins]:
                qn_net = [n for p, n in pins if p == 'QN'][0]
                bench_lines.append(f"{qn_net} = NOT({main_out})")

    # 5. Write out the .bench file
    with open(bench_file, 'w') as f:
        f.write("# ATALANTA BENCH File Generated from Yosys Netlist\n\n")
        
        for pi in inputs:
            f.write(f"INPUT({pi})\n")
            
        f.write("\n")
        
        for po in outputs:
            f.write(f"OUTPUT({po})\n")
            
        f.write("\n")
        
        for line in bench_lines:
            f.write(line + "\n")

    print(f"File Generated! Translated {len(inputs)} Inputs, {len(outputs)} Outputs, and {len(bench_lines)} Gates.")
    print(f"Saved to {bench_file}")

    # 6. Run Validation if requested
    if run_validation:
        validate_with_abc(bench_file)

# --- Execution block ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert Yosys tech-mapped Verilog to ISCAS89 BENCH format for ATALANTA."
    )
    
    parser.add_argument("--input", required=True, help="Path to the input Verilog file")
    parser.add_argument("--output", required=True, help="Path to the output BENCH file")
    # Added boolean flag for validation
    parser.add_argument("--validate", action="store_true", help="Run ABC to validate the syntax of the generated BENCH file")
    
    args = parser.parse_args()
    
    convert_verilog_to_bench(args.input, args.output, args.validate)
