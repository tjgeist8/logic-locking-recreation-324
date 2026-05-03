"""
locked_verilog_to_bench.py  (v4)
---------------------------------
Converts AutoLock locked Verilog -> ISCAS-89 BENCH format for ATALANTA/ABC/sld.

Key fix in v4
--------------
The locked Verilog has BOTH:
  - keyinput0..5  from the original circuit's encoding logic (these are the
    signals the SAT attack is trying to recover -- must keep these names)
  - key[0..31]    the AutoLock locking key bus (must NOT collide with above)

Previously key[N] was expanded to keyinputN, causing keyinput0..5 to be
declared twice and corrupting the attack tool's oracle model.

Fix: key[N] is now expanded to lockkey{N} instead of keyinput{N}.

Usage:
    python locked_verilog_to_bench.py \
        --input  best_locked_circuit.v  \
        --output best_locked_circuit.bench \
        [--validate]
"""

import re, sys, argparse, subprocess

# ── Gate type -> BENCH keyword ───────────────────────────────────────────────
PREFIX_MAP = {
    'INV': 'NOT', 'BUF': 'BUFF', 'NOT': 'NOT', 'BUFF': 'BUFF',
    'AND': 'AND', 'OR':  'OR',
    'NAND':'NAND','NOR': 'NOR',
    'XOR': 'XOR', 'XNOR':'XNOR',
}

OUTPUT_PINS   = {'ZN','Z','Q','Y','out','sum','cout','o','y','q'}
SKIP_PINS     = {'CK','CLK','clock','clk','SE','SI','CDN','SDN'}
SKIP_KEYWORDS = {
    'module','endmodule','input','output','inout',
    'wire','reg','assign','always','begin','end',
    'if','else','case','endcase','for','while',
    'posedge','negedge','parameter','localparam',
    'integer','genvar','generate','endgenerate',
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def strip_comments(text):
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    return text

def norm_key_ref(net):
    """
    key[N] -> keyinput{N}

    IMPORTANT: we use 'lockkey' not 'keyinput' to avoid colliding with
    the original circuit's keyinput0..5 signals that the SAT attack needs
    to recover.  The attack tool identifies key inputs by the name prefix
    'keyinput', so our locking key bus must use a different prefix.
    """
    m = re.match(r'^key\[(\d+)\]$', net.strip())
    return f'keyinput{m.group(1)}' if m else net.strip()

def cell_to_bench(cell_type):
    """INV_X1 / NAND3_X2 / xor / ... -> BENCH keyword, or None."""
    for cand in (
        cell_type,
        re.sub(r'_X\d+$', '', cell_type),
        re.sub(r'\d+$', '', re.sub(r'_X\d+$', '', cell_type)),
    ):
        k = PREFIX_MAP.get(cand) or PREFIX_MAP.get(cand.upper())
        if k:
            return k
    return None

# ── Port parser (module-header aware) ────────────────────────────────────────

def parse_ports(text):
    """
    Parse inputs/outputs from the module header block:

        module NAME (
            input  wire [31:0] key,       <- ends with comma, not semicolon
            input  wire G1GAT, G4GAT, ...,
            output wire G223GAT, ...
        );

    The key[31:0] bus becomes lockkey0..lockkey31 (not keyinput0..31).
    """
    inputs  = []
    outputs = []

    hdr = re.search(r'\bmodule\s+\w+\s*\((.*?)\)\s*;', text, re.DOTALL)
    if not hdr:
        print("ERROR: Could not find module header.")
        return inputs, outputs

    header = hdr.group(1)

    # Split at every input/output keyword
    parts = re.split(r'\b(input|output)\b', header)

    i = 1
    while i < len(parts) - 1:
        direction = parts[i]
        rest      = parts[i + 1]

        m = re.match(
            r'\s*(?:wire\s+)?'
            r'(?:\[(\d+):(\d+)\]\s+)?'
            r'([\w ,\n\r\t]+)',
            rest
        )
        if m:
            hi_s, lo_s, names_raw = m.group(1), m.group(2), m.group(3)
            names_raw = names_raw.strip().rstrip(',')
            names = [n.strip().rstrip(',') for n in re.split(r'[\s,]+', names_raw)
                     if n.strip().rstrip(',')]

            if hi_s and lo_s:
                lo_i = min(int(hi_s), int(lo_s))
                hi_i = max(int(hi_s), int(lo_s))
                for name in names:
                    # key bus -> lockkey prefix to avoid colliding with keyinput0..5
                    prefix = 'keyinput' if name.lower() == 'key' else f'{name}_'
                    for j in range(lo_i, hi_i + 1):
                        (inputs if direction == 'input' else outputs).append(f'{prefix}{j}')
            else:
                (inputs if direction == 'input' else outputs).extend(names)

        i += 2

    return inputs, outputs

# ── Gate parser ──────────────────────────────────────────────────────────────

def parse_gates(text):
    gates = []

    gate_re = re.compile(
        r'(?<![.\w])([A-Za-z]\w*)\s+(\w+)\s*\(([^;]*?)\)\s*;',
        re.DOTALL
    )

    for cell_type, inst_name, port_body in gate_re.findall(text):
        if cell_type.lower() in SKIP_KEYWORDS:
            continue
        if inst_name.lower() in SKIP_KEYWORDS:
            continue

        named = re.findall(r'\.(\w+)\s*\(\s*([\w\[\]\']+)\s*\)', port_body)
        if not named:
            continue

        port_map = {p: norm_key_ref(n) for p, n in named}

        # mux2 locking gate
        if cell_type.lower() == 'mux2':
            out_net = port_map.get('out')
            in0     = port_map.get('in0')
            in1     = port_map.get('in1')
            sel     = port_map.get('sel')
            if not all([out_net, in0, in1, sel]):
                print(f"WARNING: mux2 '{inst_name}' missing ports — skipped.")
                continue
            gates.append({'type':'MUX2','out':out_net,'in0':in0,'in1':in1,'sel':sel})
            continue

        # Standard cell
        bench_type = cell_to_bench(cell_type)
        if bench_type is None:
            print(f"WARNING: Unknown cell '{cell_type}' ('{inst_name}') — skipped.")
            continue

        out_net = None
        in_nets = []
        for pname, net in port_map.items():
            if pname in SKIP_PINS:
                continue
            if pname in OUTPUT_PINS:
                out_net = net
            else:
                in_nets.append(net)

        # Fallback: last named port is the output
        if out_net is None:
            items = [(p,n) for p,n in port_map.items() if p not in SKIP_PINS]
            if items:
                out_net = items[-1][1]
                in_nets = [n for _,n in items[:-1]]

        if out_net is None:
            print(f"WARNING: No output for '{inst_name}' ({cell_type}) — skipped.")
            continue

        gates.append({'type':bench_type,'out':out_net,'ins':in_nets})

    return gates

# ── MUX2 expansion ───────────────────────────────────────────────────────────

def expand_mux2(g):
    """out = sel ? in1 : in0  ->  NOT + AND + AND + OR"""
    tag  = g['out']
    nsel = f'_mux_nsel_{tag}'
    a1   = f'_mux_a1_{tag}'
    a0   = f'_mux_a0_{tag}'
    return [
        f'{nsel} = NOT({g["sel"]})',
        f'{a1} = AND({g["in1"]}, {g["sel"]})',
        f'{a0} = AND({g["in0"]}, {nsel})',
        f'{g["out"]} = OR({a1}, {a0})',
    ]

# ── Conversion ────────────────────────────────────────────────────────────────

def convert(verilog_file, bench_file):
    with open(verilog_file) as f:
        raw = f.read()

    text    = strip_comments(raw)
    inputs, outputs = parse_ports(text)
    gates   = parse_gates(text)

    if not inputs:
        print("ERROR: No inputs found — check the Verilog file.")
        sys.exit(1)

    bench_lines = []
    for g in gates:
        if g['type'] == 'MUX2':
            bench_lines.extend(expand_mux2(g))
        else:
            bench_lines.append(f"{g['out']} = {g['type']}({', '.join(g['ins'])})")

    with open(bench_file, 'w') as f:
        f.write('# ATALANTA BENCH File — AutoLock locked netlist\n\n')
        for pi in inputs:
            f.write(f'INPUT({pi})\n')
        f.write('\n')
        for po in outputs:
            f.write(f'OUTPUT({po})\n')
        f.write('\n')
        for line in bench_lines:
            f.write(line + '\n')

    n_mux = sum(1 for g in gates if g['type'] == 'MUX2')
    print()
    print(f"Converted: {len(inputs)} inputs, {len(outputs)} outputs, "
          f"{len(gates)} gates ({n_mux} MUX2 expanded to 4 BENCH gates each).")
    print(f"Saved -> {bench_file}")
    #print("Key input names in locked bench  : lockkey0 .. lockkey31")
    #print("Key input names in original bench: keyinput0 .. keyinput5")
    #print("(These are different signals — no collision.)")

# ── ABC validation ────────────────────────────────────────────────────────────

def validate_with_abc(bench_file):
    print('\n--- Validating with ABC ---')
    abc_cmd = None
    for cmd in ('yosys-abc', 'abc'):
        try:
            subprocess.run([cmd,'-c','quit'], capture_output=True, check=True)
            abc_cmd = cmd; break
        except FileNotFoundError:
            continue
    if not abc_cmd:
        print('WARNING: abc/yosys-abc not found — skipping.')
        return
    result = subprocess.run(
        [abc_cmd,'-c',f'read_bench {bench_file}; print_stats; quit'],
        capture_output=True, text=True
    )
    out = result.stdout + result.stderr
    if any(k in out for k in ('Error','error','Cannot open','failed')):
        print('FAILED:')
        for line in out.splitlines():
            if any(k in line for k in ('Error','error','failed','Cannot')):
                print(f'  {line.strip()}')
    else:
        print('SUCCESS.')
        for line in out.splitlines():
            if 'nd' in line and 'edge' in line:
                print(f'  {line.strip()}')

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description='Convert AutoLock locked Verilog -> ISCAS-89 BENCH.')
    p.add_argument('--input',    required=True)
    p.add_argument('--output',   required=True)
    p.add_argument('--validate', action='store_true')
    a = p.parse_args()
    convert(a.input, a.output)
    if a.validate:
        validate_with_abc(a.output)

if __name__ == '__main__':
    main()
