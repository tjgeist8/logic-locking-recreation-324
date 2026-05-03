"""
verilog_to_bench.py
--------------------
Converts synthesized/locked Verilog -> ISCAS-89 BENCH format.
"""

import re
import sys
import argparse

# ── Gate type -> BENCH keyword ────────────────────────────────────────────────

PREFIX_MAP = {
    'INV':  'NOT',  'BUF':  'BUFF', 'NOT':  'NOT',  'BUFF': 'BUFF',
    'AND':  'AND',  'OR':   'OR',
    'NAND': 'NAND', 'NOR':  'NOR',
    'XOR':  'XOR',  'XNOR': 'XNOR',
}

OUTPUT_PINS = {'ZN', 'Z', 'Q', 'QN', 'Y', 'out', 'sum', 'cout', 'o', 'y', 'q'}
SKIP_PINS   = {'CK', 'CLK', 'clock', 'clk', 'SE', 'SI', 'CDN', 'SDN'}

SKIP_KEYWORDS = {
    'module', 'endmodule', 'input', 'output', 'inout', 'wire', 'reg',
    'assign', 'always', 'begin', 'end', 'if', 'else', 'case', 'endcase',
    'for', 'while', 'posedge', 'negedge', 'parameter', 'localparam',
    'integer', 'genvar', 'generate', 'endgenerate',
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def strip_comments(text):
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    return text


def norm_net(net):
    """
    Normalize a net name:
      1. Strip Yosys backslashes and spaces
      2. Match key[N] or keyinput[N] and force to keyinputN
      3. Replace any remaining [ or ] with underscores
    """
    net = net.replace('\\', '').strip()
    
    m = re.match(r'^(?:key|keyinput)\[(\d+)\]$', net)
    if m:
        return f'keyinput{m.group(1)}'
        
    net = net.replace('[', '_').replace(']', '_')
    return net


def cell_to_bench(cell_type):
    for cand in (
        cell_type,
        re.sub(r'_X\d+$', '', cell_type),
        re.sub(r'\d+$', '', re.sub(r'_X\d+$', '', cell_type)),
    ):
        k = PREFIX_MAP.get(cand) or PREFIX_MAP.get(cand.upper())
        if k:
            return k
    return None

# ── Port parser (body-style declarations) ─────────────────────────────────────

def parse_ports(text):
    inputs  = []
    outputs = []

    # FIX: Use [^;]+ to ensure we catch backslash-escaped names from Yosys!
    port_re = re.compile(
        r'\b(input|output)\b'
        r'(?:\s+wire\b)?'
        r'(?:\s+\[(\d+):(\d+)\])?'
        r'\s+([^;]+);'
    )

    for direction, hi_s, lo_s, names_raw in port_re.findall(text):
        names = [n.strip() for n in names_raw.split(',') if n.strip()]

        if hi_s and lo_s:
            lo_i = min(int(hi_s), int(lo_s))
            hi_i = max(int(hi_s), int(lo_s))
            for name in names:
                clean_name = name.replace('\\', '').strip()
                is_key = clean_name.lower() in ('key', 'keyinput')
                
                for i in range(lo_i, hi_i + 1):
                    entry = f'keyinput{i}' if is_key else f'{clean_name}_{i}'
                    (inputs if direction == 'input' else outputs).append(entry)
        else:
            for name in names:
                clean_name = name.replace('\\', '').strip()
                clean_name = re.sub(r'^(key|keyinput)\[(\d+)\]$', r'keyinput\2', clean_name)
                clean_name = clean_name.replace('[', '_').replace(']', '_')
                (inputs if direction == 'input' else outputs).append(clean_name)

    seen = set()
    inputs_dedup = []
    for x in inputs:
        if x not in seen:
            seen.add(x)
            inputs_dedup.append(x)

    seen = set()
    outputs_dedup = []
    for x in outputs:
        if x not in seen:
            seen.add(x)
            outputs_dedup.append(x)

    return inputs_dedup, outputs_dedup

# ── Gate parser ───────────────────────────────────────────────────────────────

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

        named = re.findall(r'\.(\w+)\s*\(\s*([\w\[\]\\\'\s]+)\s*\)', port_body)
        if not named:
            continue

        port_map = {p: norm_net(n) for p, n in named}

        bench_type = cell_to_bench(cell_type)
        if bench_type is None:
            continue

        out_net  = None
        in_nets  = []

        for pname, net in port_map.items():
            if pname in SKIP_PINS:
                continue
            if pname in OUTPUT_PINS:
                out_net = net
            else:
                in_nets.append(net)

        if out_net is None:
            items = [(p, n) for p, n in port_map.items() if p not in SKIP_PINS]
            if items:
                out_net = items[-1][1]
                in_nets = [n for _, n in items[:-1]]

        if out_net is None:
            continue

        gates.append({'type': bench_type, 'out': out_net, 'ins': in_nets})

    return gates

# ── Conversion ────────────────────────────────────────────────────────────────

def convert(verilog_file, bench_file):
    with open(verilog_file) as f:
        raw = f.read()

    text = strip_comments(raw)
    inputs, outputs = parse_ports(text)
    gates = parse_gates(text)

    if not inputs:
        print("ERROR: No inputs found — check the Verilog file.")
        sys.exit(1)
    if not outputs:
        print("ERROR: No outputs found — check the Verilog file.")
        sys.exit(1)

    with open(bench_file, 'w') as f:
        f.write('# ATALANTA BENCH — converted from synthesized Verilog\n\n')
        for pi in inputs:
            f.write(f'INPUT({pi})\n')
        f.write('\n')
        for po in outputs:
            f.write(f'OUTPUT({po})\n')
        f.write('\n')
        for g in gates:
            f.write(f"{g['out']} = {g['type']}({', '.join(g['ins'])})\n")

    print(f"Inputs : {len(inputs)}")
    print(f"Outputs: {len(outputs)}")
    print(f"Gates  : {len(gates)}")
    print(f"Saved  -> {bench_file}")

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description='Convert synthesized/locked Verilog -> ISCAS-89 BENCH.')
    p.add_argument('--input',  required=True,  help='Input Verilog file')
    p.add_argument('--output', required=True,  help='Output BENCH file')
    a = p.parse_args()
    convert(a.input, a.output)

if __name__ == '__main__':
    main()
