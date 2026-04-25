#!/usr/bin/env python3
"""
CAS-Lock Logic Locking Tool
============================
Applies the CAS-Lock (Cascaded Locking) scheme to a gate-level Verilog netlist.

Based on:
  Shakya et al., "CAS-Lock: A Security-Corruptibility Trade-off Resilient Logic
  Locking Scheme", IACR TCHES 2020, Vol. 2020, No. 1, pp. 175-202.

Architecture
------------
CAS-Lock appends a block containing two complementary cascaded Boolean
functions, gcas and gcas_bar, whose outputs are ANDed together as a flip
signal Y:

    Y = gcas(IN XOR K1)  AND  gcas_bar(IN XOR K2)

where:
  - gcas is a cascade of AND/OR gates (daisy-chained, not tree).
  - gcas_bar uses the IDENTICAL gate cascade as gcas, but its final output
    is INVERTED, making gcas_bar = NOT gcas.
  - The correct key is K1 = K2 (call it K_half of length N).
    Then gcas_bar(X XOR K2) = NOT gcas(X XOR K1), so
    Y = gcas AND NOT(gcas) = 0 for EVERY input pattern.

  => The circuit output is never corrupted when the correct key is applied.

  For any wrong key (K1_w, K2_w) != (K_half, K_half), there exists at least
  one unique input pattern where Y=1, flipping the output. The SAT attacker
  must enumerate 2^N patterns to rule out all wrong keys (brute force).

Key layout (2N bits):
    [key_g_0 ... key_g_{N-1}   key_gb_0 ... key_gb_{N-1}]
  Correct key: key_g_i = key_gb_i = K_half[i] for all i.

Output injection:
    The flip signal Y is XOR'd into a primary output net.  With the correct
    key Y=0, so the XOR is transparent and the circuit is fully functional.

Usage
-----
    python cas_lock.py [options] <input.v>

Options:
    -o, --output FILE       Output file (default: <input>_caslocked.v)
    -n, --num-inputs INT    Number of primary inputs used by CAS-Lock (default: 4)
    -p, --p-value INT       Desired output-1 count p of gcas.
                            Controls corruptibility: higher p -> harder bypass attack.
                            Range: 1 .. 2^N - 1  (default: N, moderate).
    -s, --seed INT          Random seed for reproducibility (default: 42)
    --target-output STR     Output net to inject Y into (default: first output port)
    --key STR               Comma-separated N correct half-key bits, e.g. 1,0,1,0
                            (the tool uses this for BOTH halves K1=K2=key).
                            If omitted, a random key is generated.
"""

import re
import sys
import argparse
import random
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# VERILOG MODULE
# Create a dataclass to represent the parsed Verilog module
# inludes the name as a string, the lists of other important module elements.

@dataclass
class VerilogModule:
    name: str
    inputs: List[str]                   = field(default_factory=list)
    outputs: List[str]                  = field(default_factory=list)
    wires: List[str]                    = field(default_factory=list)
    instances: List[str]                = field(default_factory=list)
    header_comments: List[str]          = field(default_factory=list)
    bus_wires: List[Tuple[str,int,int]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Verilog parser  (gate-level structural netlist)
# ---------------------------------------------------------------------------

_KW = frozenset(['wire','input','output','inout','reg','assign',
                 'always','initial','parameter','localparam'])

def parse_verilog(text: str) -> VerilogModule:
    mod = VerilogModule(name="")
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    mod.header_comments = [ln for ln in text.splitlines() if ln.strip().startswith('//')]

    m = re.search(r'\bmodule\s+(\w+)\s*\(', text)
    if not m:
        raise ValueError("Cannot find 'module' declaration")
    mod.name = m.group(1)

    for m in re.finditer(r'\b(input|output)\s+(?:\[\d+:\d+\]\s+)?(\w+)\s*;', text):
        (mod.inputs if m.group(1) == 'input' else mod.outputs).append(m.group(2))

    for m in re.finditer(r'\bwire\s+(?:\[(\d+):(\d+)\]\s+)?(\w+)\s*;', text):
        if m.group(1) is not None:
            mod.bus_wires.append((m.group(3), int(m.group(1)), int(m.group(2))))
        else:
            mod.wires.append(m.group(3))

    body_m = re.search(r'\bmodule\b.*?\(.*?\);(.*?)\bendmodule\b', text, re.DOTALL)
    if not body_m:
        raise ValueError("Cannot find module body")

    for m in re.finditer(r'(\w+)\s+(\w+)\s*\((.*?)\)\s*;', body_m.group(1), re.DOTALL):
        if m.group(1) not in _KW:
            mod.instances.append(m.group(0).strip())

    return mod


# ---------------------------------------------------------------------------
# Gate sequence computation
# ---------------------------------------------------------------------------

def simulate_gcas(gate_seq: List[str], N: int) -> int:
    """Count patterns for which gcas evaluates to 1."""
    count = 0
    for pat in range(1 << N):
        bits = [(pat >> i) & 1 for i in range(N)]
        val = bits[0]
        for i, g in enumerate(gate_seq):
            val = (val & bits[i+1]) if g == 'AND' else (val | bits[i+1])
        count += val
    return count


def build_gate_sequence(N: int, target_p: int) -> List[str]:
    """
    Build a gate sequence of length N-1 targeting output-1 count >= target_p.
    Strategy: start all-AND (p=1), flip gates to OR from the output end.
    """
    gates = ['AND'] * (N - 1)
    for i in range(N - 2, -1, -1):
        if simulate_gcas(gates, N) >= target_p:
            break
        gates[i] = 'OR'
    return gates


# ---------------------------------------------------------------------------
# CAS-Lock block generator
# ---------------------------------------------------------------------------

class CASLockBuilder:
    """
    Emits NanGate-compatible standard-cell Verilog for a CAS-Lock block.

    Correct key construction:  K1 = K2 = k_half
        L  = X XOR k_half  (same L for both halves)
        gcas(L)     = cascaded AND/OR of L bits
        gcas_bar(L) = NOT( gcas(L) )      [INV on final cascade output]
        Y = gcas AND gcas_bar = gcas AND NOT(gcas) = 0  for ALL inputs  OK
    """

    def __init__(self, selected_inputs: List[str],
                 gate_seq: List[str], k_half: List[int]):
        self.inputs    = selected_inputs
        self.N         = len(selected_inputs)
        self.gate_seq  = gate_seq      # length N-1
        self.k_half    = k_half        # length N
        self._uid      = 0
        self.new_wires: List[str] = []
        self.new_insts: List[str] = []

    def _w(self, tag: str = "") -> str:
        name = f"_cas_w{self._uid:04d}_{tag}_"
        self._uid += 1
        self.new_wires.append(name)
        return name

    def _iname(self, tag: str = "") -> str:
        name = f"_cas_i{self._uid:04d}_{tag}_"
        self._uid += 1
        return name

    def _emit(self, cell: str, inst: str, **ports) -> None:
        conn = "\n".join(f"    .{p}({n})" for p, n in ports.items())
        self.new_insts.append(f"  {cell} {inst} (\n{conn}\n  );")

    def _xor_key(self, in_net: str, key_port: str) -> str:
        out = self._w("xk")
        self._emit("XOR2_X1", self._iname("xor"), A=in_net, B=key_port, Z=out)
        return out

    def _cascade(self, keyed: List[str], label: str) -> str:
        val = keyed[0]
        for idx, g in enumerate(self.gate_seq):
            out = self._w(f"{label}_g{idx}")
            if g == 'AND':
                self._emit("AND2_X1", self._iname(f"{label}g{idx}"),
                           A1=val, A2=keyed[idx+1], ZN=out)
            else:
                self._emit("OR2_X1",  self._iname(f"{label}g{idx}"),
                           A1=val, A2=keyed[idx+1], ZN=out)
            val = out
        return val

    def build(self) -> Tuple[List[str], List[str], str]:
        # gcas half  (key ports: key_g_0 .. key_g_{N-1})
        keyed_g = [self._xor_key(self.inputs[i], f"key_g_{i}") for i in range(self.N)]
        g_out   = self._cascade(keyed_g, "g")

        # gcas_bar half  (key ports: key_gb_0 .. key_gb_{N-1})
        keyed_gb       = [self._xor_key(self.inputs[i], f"key_gb_{i}") for i in range(self.N)]
        gb_cascade_out = self._cascade(keyed_gb, "gb")

        # Invert to form gcas_bar = NOT(cascade output)
        gb_out = self._w("gb_inv")
        self._emit("INV_X1", self._iname("gb_inv"), A=gb_cascade_out, ZN=gb_out)

        # Y = gcas AND gcas_bar
        y_net = self._w("Y")
        self._emit("AND2_X1", self._iname("andY"), A1=g_out, A2=gb_out, ZN=y_net)

        return self.new_wires, self.new_insts, y_net

    def key_port_names(self) -> List[str]:
        return ([f"key_g_{i}"  for i in range(self.N)] +
                [f"key_gb_{i}" for i in range(self.N)])

    def correct_key_bits(self) -> List[int]:
        return list(self.k_half) + list(self.k_half)


# ---------------------------------------------------------------------------
# Output injection
# ---------------------------------------------------------------------------

_OUT_PORTS = ('ZN', 'Z', 'Q', 'CO', 'S')

def inject_y_into_output(instances: List[str],
                          target: str,
                          y_net: str) -> Tuple[List[str], str]:
    intermediate = f"_cas_prexor_{target}_"
    patched = list(instances)
    found   = False

    for idx, inst in enumerate(patched):
        for op in _OUT_PORTS:
            pat = re.compile(
                r'(\.' + op + r'\s*\(\s*)' + re.escape(target) + r'(\s*\))'
            )
            new_inst, n = pat.subn(r'\g<1>' + intermediate + r'\g<2>', inst)
            if n:
                patched[idx] = new_inst
                found = True
                break
        if found:
            break

    if not found:
        raise ValueError(
            f"Could not find a driver for output '{target}'. "
            f"Try --target-output with another port name."
        )

    patched.append(
        f"  XOR2_X1 _cas_out_xor_ (\n"
        f"    .A({intermediate}),\n"
        f"    .B({y_net}),\n"
        f"    .Z({target})\n"
        f"  );"
    )
    return patched, intermediate


# ---------------------------------------------------------------------------
# Functional verification
# ---------------------------------------------------------------------------

def verify_correct_key(gate_seq: List[str], N: int, k_half: List[int]) -> bool:
    """Y must be 0 for all 2^N patterns when K1=K2=k_half."""
    def gcas(bits):
        val = bits[0]
        for i, g in enumerate(gate_seq):
            val = (val & bits[i+1]) if g == 'AND' else (val | bits[i+1])
        return val

    for pat in range(1 << N):
        bits = [(pat >> i) & 1 for i in range(N)]
        L    = [bits[i] ^ k_half[i] for i in range(N)]
        g    = gcas(L)
        gb   = 1 - gcas(L)   # NOT gcas, same L because K1=K2
        if g & gb:
            return False
    return True


# ---------------------------------------------------------------------------
# Verilog emitter
# ---------------------------------------------------------------------------

def emit_locked_verilog(module: VerilogModule,
                         patched_insts: List[str],
                         cas_wires: List[str],
                         cas_insts: List[str],
                         intermediate_wire: str,
                         key_ports: List[str],
                         gate_seq: List[str],
                         actual_p: int,
                         N: int,
                         k_half: List[int],
                         correct_key_2n: List[int],
                         selected_inputs: List[str],
                         target_output: str) -> str:

    hex_w   = math.ceil(2 * N / 4)
    hex_val = int(''.join(str(b) for b in correct_key_2n), 2)
    hex_str = f"0x{hex_val:0{hex_w}X}"

    lines = []
    lines += module.header_comments
    lines += [
        "",
        "// " + "=" * 60,
        "//  CAS-Lock applied by cas_lock.py",
        "//  Reference: Shakya et al., IACR TCHES 2020, pp. 175-202",
        "// " + "-" * 60,
        f"//  N (CAS-Lock inputs)  : {N}",
        f"//  Key size (2N bits)   : {2*N}",
        f"//  Gate sequence (gcas) : {' -> '.join(gate_seq)}",
        f"//  p-value (gcas)       : {actual_p}  / 2^{N} = {1<<N}",
        f"//  Corruptibility       : {actual_p/(1<<N)*100:.1f}%",
        f"//  CAS-Lock input nets  : {', '.join(selected_inputs)}",
        f"//  Target output net    : {target_output}",
        f"//  Correct key (hex)    : {hex_str}",
        f"//  Correct key (bits)   : {' '.join(str(b) for b in correct_key_2n)}",
        f"//  Key port order       : {', '.join(key_ports)}",
        f"//  SAT resistance       : 2^N - 1 = {(1<<N)-1} iterations",
        "// " + "=" * 60,
        "",
    ]

    all_ports = module.inputs + module.outputs + key_ports
    lines.append(f"module {module.name}(")
    lines.append(",\n".join(f"  {p}" for p in all_ports))
    lines.append(");")
    lines.append("")

    lines.append("  // --- Original ports ---")
    for inp in module.inputs:
        lines += [f"  input {inp};", f"  wire {inp};"]
    for out in module.outputs:
        lines += [f"  output {out};", f"  wire {out};"]
    lines.append("")

    lines.append("  // --- CAS-Lock key input ports (2N = {0} bits) ---".format(2 * N))
    for kp in key_ports:
        lines += [f"  input {kp};", f"  wire {kp};"]
    lines.append("")

    lines.append("  // --- Original internal wires ---")
    for w in module.wires:
        lines.append(f"  wire {w};")
    for bname, hi, lo in module.bus_wires:
        lines.append(f"  wire [{hi}:{lo}] {bname};")
    lines.append("")

    lines.append("  // --- CAS-Lock internal wires ---")
    lines.append(f"  wire {intermediate_wire};")
    for w in cas_wires:
        lines.append(f"  wire {w};")
    lines.append("")

    lines.append("  // --- Original gate instances (with output injection) ---")
    for inst in patched_insts:
        lines.append(f"  {inst}")
    lines.append("")

    lines.append("  // --- CAS-Lock gate instances ---")
    for inst in cas_insts:
        lines.append(inst)
    lines.append("")

    lines.append("endmodule")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level locking function
# ---------------------------------------------------------------------------

def apply_cas_lock(module: VerilogModule,
                   N: int,
                   target_p: int,
                   k_half: Optional[List[int]],
                   target_output: Optional[str],
                   rng: random.Random) -> str:

    # Select N primary inputs
    data_inputs = [i for i in module.inputs
                   if i.lower() not in ('clock','clk','reset','rst','set')]
    clk_rst     = [i for i in module.inputs if i not in data_inputs]

    if len(data_inputs) >= N:
        selected = rng.sample(data_inputs, N)
    else:
        selected = data_inputs + clk_rst[:N - len(data_inputs)]
    if len(selected) < 2:
        raise ValueError(f"Need >= 2 primary inputs; found {len(selected)}")
    actual_N = len(selected)

    # Target output
    if target_output is None:
        target_output = module.outputs[0] if module.outputs else None
    if not target_output:
        raise ValueError("No output ports found in the module.")
    if target_output not in module.outputs:
        raise ValueError(f"'{target_output}' is not in {module.outputs}")

    # Half-key
    if k_half is None:
        k_half = [rng.randint(0, 1) for _ in range(actual_N)]
    if len(k_half) != actual_N:
        raise ValueError(f"Half-key must have {actual_N} bits, got {len(k_half)}")

    # Gate sequence
    target_p = max(1, min(target_p, (1 << actual_N) - 1))
    gate_seq  = build_gate_sequence(actual_N, target_p)
    actual_p  = simulate_gcas(gate_seq, actual_N)

    # Sanity check
    if not verify_correct_key(gate_seq, actual_N, k_half):
        raise RuntimeError("INTERNAL ERROR: correct key check failed!")

    # Build CAS-Lock block
    builder        = CASLockBuilder(selected, gate_seq, k_half)
    cas_wires, cas_insts, y_net = builder.build()
    key_ports      = builder.key_port_names()
    correct_key_2n = builder.correct_key_bits()

    # Inject Y into target output
    patched_insts, intermediate_wire = inject_y_into_output(
        module.instances, target_output, y_net
    )

    # Emit Verilog
    return emit_locked_verilog(
        module, patched_insts, cas_wires, cas_insts,
        intermediate_wire, key_ports, gate_seq,
        actual_p, actual_N, k_half, correct_key_2n,
        selected, target_output
    )


# ---------------------------------------------------------------------------
# Key report
# ---------------------------------------------------------------------------

def print_key_report(module_name, N, k_half, key_ports, correct_key_2n,
                     gate_seq, actual_p, target_output, selected_inputs):
    W = 64
    print()
    print("=" * W)
    print("  CAS-Lock Applied Successfully")
    print("=" * W)
    print(f"  Module            : {module_name}")
    print(f"  CAS inputs (N)    : {N}  ->  key size 2N = {2*N} bits")
    print(f"  CAS input nets    : {', '.join(selected_inputs)}")
    print(f"  Target output     : {target_output}")
    print(f"  Gate sequence     : {' -> '.join(gate_seq)}")
    print(f"  p-value (gcas)    : {actual_p}  /  2^{N} = {1<<N}")
    print(f"  Corruptibility    : {actual_p/(1<<N)*100:.1f}%  (higher -> harder bypass)")
    print()
    hex_w   = math.ceil(2 * N / 4)
    hex_val = int(''.join(str(b) for b in correct_key_2n), 2)
    print("  Correct key  [KEEP SECRET]")
    print(f"    Half-key K  : {' '.join(str(b) for b in k_half)}")
    print(f"    Full 2N-key : {' '.join(str(b) for b in correct_key_2n)}")
    print(f"    Hex         : 0x{hex_val:0{hex_w}X}")
    print()
    print("  Port name             Correct bit   Role")
    print("  " + "-" * 46)
    for i, (port, bit) in enumerate(zip(key_ports, correct_key_2n)):
        role = f"K1[{i}]" if i < N else f"K2[{i-N}]"
        print(f"  {port:<22s}  {bit}             {role}")
    print()
    print(f"  SAT resistance : 2^N - 1 = {(1<<N)-1:,} forced iterations (brute force)")
    print("=" * W)
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    ap = argparse.ArgumentParser(
        description="Apply CAS-Lock logic locking to a gate-level Verilog netlist.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("input", help="Input Verilog netlist (.v)")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("-n", "--num-inputs", type=int, default=4)
    ap.add_argument("-p", "--p-value", type=int, default=None)
    ap.add_argument("-s", "--seed", type=int, default=42)
    ap.add_argument("--target-output", default=None)
    ap.add_argument("--key", default=None,
                    help="N comma-separated half-key bits (K1=K2=key)")
    return ap.parse_args()


def main():
    args = parse_args()
    rng  = random.Random(args.seed)

    print(f"[CAS-Lock] Reading {args.input} ...")
    with open(args.input) as f:
        text = f.read()

    module = parse_verilog(text)
    print(f"[CAS-Lock] Parsed module '{module.name}': "
          f"{len(module.inputs)} inputs, {len(module.outputs)} outputs, "
          f"{len(module.instances)} instances")

    N = args.num_inputs
    if N > len(module.inputs):
        print(f"[CAS-Lock] WARNING: N={N} > available inputs; reducing to {len(module.inputs)}")
        N = len(module.inputs)
    if N < 2:
        print("[CAS-Lock] ERROR: need at least 2 inputs.")
        sys.exit(1)

    target_p = args.p_value if args.p_value is not None else N

    k_half = None
    if args.key:
        k_half = [int(b.strip()) for b in args.key.split(',')]
        if len(k_half) != N:
            print(f"[CAS-Lock] ERROR: --key must have {N} bits, got {len(k_half)}")
            sys.exit(1)

    print(f"[CAS-Lock] Applying CAS-Lock (N={N}, target p~{target_p}) ...")
    locked = apply_cas_lock(module, N, target_p, k_half, args.target_output, rng)

    # Parse summary from emitted header for the report
    def _re(pattern, default=""):
        m = re.search(pattern, locked)
        return m.group(1).strip() if m else default

    raw_key  = _re(r'Correct key \(bits\)\s*:\s*([\d ]+)')
    raw_ports= _re(r'Key port order\s*:\s*(.+)')
    raw_gates= _re(r'Gate sequence \(gcas\)\s*:\s*(.+)')
    raw_p    = _re(r'p-value \(gcas\)\s*:\s*(\d+)', str(target_p))
    raw_inps = _re(r'CAS-Lock input nets\s*:\s*(.+)')
    raw_tgt  = _re(r'Target output net\s*:\s*(\S+)')

    final_key  = [int(b) for b in raw_key.split()] if raw_key else []
    final_ports= [s.strip() for s in raw_ports.split(',')] if raw_ports else []
    final_gates= [s.strip() for s in raw_gates.split('->')] if raw_gates else []
    final_p    = int(raw_p)
    final_inps = [s.strip() for s in raw_inps.split(',')] if raw_inps else []
    final_N    = len(final_inps) if final_inps and final_inps[0] else N
    final_half = final_key[:final_N] if final_key else []

    print_key_report(module.name, final_N, final_half, final_ports,
                     final_key, final_gates, final_p, raw_tgt, final_inps)

    out_path = args.output or args.input.replace('.v', '_caslocked.v')
    with open(out_path, 'w') as f:
        f.write(locked)
    print(f"[CAS-Lock] Locked netlist written -> {out_path}")


if __name__ == "__main__":
    main()
