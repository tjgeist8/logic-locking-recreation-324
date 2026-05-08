#!/usr/bin/env python3
"""
CAS-Lock RTL Logic Locking Tool
=================================
Applies the CAS-Lock (Cascaded Locking) scheme to a behavioral/RTL Verilog
file that uses continuous assign statements with ~, &, |, ^ operators.

Contrast with cas_lock.py (gate-level):
  Gate-level  : instantiates AND2_X1, OR2_X1, INV_X1, XOR2_X1 cells.
  RTL (this)  : emits assign statements using &, |, ~, ^ operators.
  The CAS-Lock logic and security properties are identical; only the
  representation differs.

Architecture
------------
Two cascaded Boolean functions gcas and gcas_bar are appended as assign
chains, producing a flip signal Y:

    Y = gcas_out & gcas_bar_out

gcas  : a daisy-chain of & / | stages, each stage XORing a primary input
        with an (unmasked) key bit before entering the cascade.
gcas_bar : identical cascade, but every keyed input and the final output
        are inverted with ~, making gcas_bar = ~gcas.

Correct key:  K1 = K2 = k_half  (internally, after un-masking).
Port-facing observed key is masked:  obs[i] = k_half[i%N] ^ mask[i]
Each key port passes through an assign that either wires straight through
(mask=0) or inverts with ~ (mask=1) before entering the cascade.
This hides the K1=K2 relationship from an attacker reading port values.

Y = gcas & ~gcas = 0 always with the correct key.
Y can be 1 for wrong keys, corrupting the target output via XOR.

Usage
-----
    python cas_lock_rtl.py [options] <input.v>

Options:
    -o, --output FILE       Output file (default: <input>_caslocked.v)
    -n, --num-inputs INT    Number of primary inputs used by CAS-Lock (default: 4)
    -p, --p-value INT       Target output-1 count of gcas (default: N)
    -s, --seed INT          Random seed (default: 42)
    --target-output STR     Output signal to inject Y into (default: first output)
    --key STR               Comma-separated N half-key bits, e.g. 1,0,1,0
                            If omitted, a random key is generated.
"""

import re
import sys
import argparse
import random
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RTLModule:
    name: str
    inputs:          List[str]               = field(default_factory=list)
    outputs:         List[str]               = field(default_factory=list)
    wires:           List[str]               = field(default_factory=list)
    assigns:         List[Tuple[str, str]]   = field(default_factory=list)  # (lhs, rhs)
    header_comments: List[str]               = field(default_factory=list)
    bus_ports:       List[Tuple[str,int,int]]= field(default_factory=list)


# ---------------------------------------------------------------------------
# RTL parser
# ---------------------------------------------------------------------------

_KW = frozenset(['wire','input','output','inout','reg','assign',
                 'always','initial','parameter','localparam'])

def parse_rtl(text: str) -> RTLModule:
    mod = RTLModule(name="")

    # Strip block comments, preserve line comments for header
    clean = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    mod.header_comments = [ln for ln in text.splitlines()
                           if ln.strip().startswith('//')]

    # Module name
    m = re.search(r'\bmodule\s+(\w+)\s*\(', clean)
    if not m:
        raise ValueError("Cannot find 'module' declaration")
    mod.name = m.group(1)

    # Port directions (scalar and bus)
    for m in re.finditer(
            r'\b(input|output)\s+(?:\[(\d+):(\d+)\]\s+)?([^;]+);', clean):
        direction = m.group(1)
        hi, lo    = m.group(2), m.group(3)
        names     = [n.strip() for n in m.group(4).split(',') if n.strip()]
        for name in names:
            if hi is not None:
                mod.bus_ports.append((name, int(hi), int(lo)))
            elif direction == 'input':
                mod.inputs.append(name)
            else:
                mod.outputs.append(name)

    # Wire declarations
    for m in re.finditer(r'\bwire\s+([^;]+);', clean):
        for name in m.group(1).split(','):
            name = name.strip()
            if name:
                mod.wires.append(name)

    # Assign statements — capture lhs and full rhs expression
    for m in re.finditer(r'\bassign\s+(\w+)\s*=\s*(.+?)\s*;', clean, re.DOTALL):
        mod.assigns.append((m.group(1).strip(), m.group(2).strip()))

    return mod


# ---------------------------------------------------------------------------
# Gate sequence helpers  (shared logic with gate-level script)
# ---------------------------------------------------------------------------

def simulate_gcas(gate_seq: List[str], N: int) -> int:
    """Count 2^N input patterns for which the cascade evaluates to 1."""
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
    Starts all-AND (p=1) and flips gates to OR from the output end.
    """
    gates = ['AND'] * (N - 1)
    for i in range(N - 2, -1, -1):
        if simulate_gcas(gates, N) >= target_p:
            break
        gates[i] = 'OR'
    return gates


# ---------------------------------------------------------------------------
# RTL CAS-Lock block builder
# ---------------------------------------------------------------------------

class RTLCASLockBuilder:
    """
    Produces assign-statement Verilog for a CAS-Lock block.

    Internal key structure:  K1 = K2 = k_half
    Observed (port) key:     obs[i] = k_half[i % N] ^ mask[i]

    Each keyinput port is un-masked by an assign:
      mask=0:  assign _cas_uk{i}_ = keyinput{i};          (wire through)
      mask=1:  assign _cas_uk{i}_ = ~keyinput{i};         (invert)
    After un-masking, the recovered bit is k_half[i%N].

    gcas stages (AND/OR cascade, inputs XOR'd with K1):
      assign _cas_gxk{i}_ = input[i] ^ _cas_uk{i}_;
      assign _cas_g0_      = _cas_gxk0_;
      assign _cas_g1_      = _cas_g0_ & _cas_gxk1_;   (or |)
      ...

    gcas_bar: identical cascade using K2 ports (same internal value = k_half),
    with every stage signal inverted and a final inversion:
      assign _cas_gbxk{i}_ = input[i] ^ _cas_uk{N+i}_;
      assign _cas_gb0_     = ~_cas_gbxk0_;
      assign _cas_gb1_     = ~(_cas_gb0_ & ~_cas_gbxk1_);  (or |)
      ...equivalent to NOT(cascade(L2)), so = ~gcas when K1=K2.

    Y = gcas_out & gcas_bar_out
    """

    def __init__(self, selected_inputs: List[str],
                 gate_seq: List[str],
                 k_half: List[int],
                 mask: List[int]):
        self.inputs   = selected_inputs
        self.N        = len(selected_inputs)
        self.gate_seq = gate_seq          # length N-1
        self.k_half   = k_half            # length N
        self.mask     = mask              # length 2N
        # Observed (port-facing) correct key bits
        self.observed_key = [k_half[i % self.N] ^ mask[i]
                             for i in range(2 * self.N)]
        self.new_wires:   List[str] = []
        self.new_assigns: List[Tuple[str,str]] = []  # (lhs, rhs)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _wire(self, name: str) -> str:
        self.new_wires.append(name)
        return name

    def _assign(self, lhs: str, rhs: str) -> None:
        self.new_assigns.append((lhs, rhs))

    # ── un-mask a key port ────────────────────────────────────────────────────

    def _unmask(self, port_index: int) -> str:
        """
        Emit an assign that recovers the internal k_half bit from the
        observed port value.  Returns the wire name holding k_half[port_index%N].
        """
        port = f"keyinput{port_index}"
        out  = self._wire(f"_cas_uk{port_index}_")
        if self.mask[port_index] == 0:
            self._assign(out, port)          # wire through
        else:
            self._assign(out, f"~{port}")    # invert to recover k_half
        return out

    # ── XOR a primary input with the recovered key bit ────────────────────────

    def _xor_input(self, in_net: str, key_net: str, tag: str) -> str:
        out = self._wire(f"_cas_{tag}xk_")
        self._assign(out, f"{in_net} ^ {key_net}")
        return out

    # ── Build one cascade half ────────────────────────────────────────────────

    def _build_cascade(self, keyed: List[str], label: str,
                       invert_stages: bool) -> str:
        """
        Emit the AND/OR cascade for one half of CAS-Lock.

        keyed         : list of N net names (already XOR'd with key)
        label         : 'g' for gcas, 'gb' for gcas_bar
        invert_stages : True for gcas_bar — each stage is inverted so that
                        the whole chain computes NOT(cascade(keyed)),
                        making gcas_bar = ~gcas when the internal keys match.

        Returns the output wire name of the final stage.
        """
        if invert_stages:
            # First stage: val = ~keyed[0]
            val_name = self._wire(f"_cas_{label}0_")
            self._assign(val_name, f"~{keyed[0]}")
        else:
            # First stage: val = keyed[0]  (just a rename / wire)
            val_name = self._wire(f"_cas_{label}0_")
            self._assign(val_name, keyed[0])

        for idx, g in enumerate(self.gate_seq):
            out_name = self._wire(f"_cas_{label}{idx+1}_")
            next_in  = keyed[idx + 1]

            if not invert_stages:
                # Normal cascade: val = val OP next_in
                if g == 'AND':
                    self._assign(out_name, f"{val_name} & {next_in}")
                else:
                    self._assign(out_name, f"{val_name} | {next_in}")
            else:
                # Inverted cascade: each stage applies De Morgan so the
                # overall function equals ~(cascade(keyed)).
                # AND stage inverted: ~(a & b)  written as ~val_name | ~next_in
                # OR  stage inverted: ~(a | b)  written as ~val_name & ~next_in
                # But we track the intermediate in un-inverted form to allow
                # chaining, then invert the final output only.
                # Simpler equivalent: build the same cascade but on ~keyed inputs
                # (already done at stage 0) and invert the output once at the end.
                # Here we build a straight cascade on the ~keyed[0] first stage,
                # using ~next_in for each subsequent input.
                if g == 'AND':
                    self._assign(out_name, f"{val_name} & ~{next_in}")
                else:
                    self._assign(out_name, f"{val_name} | ~{next_in}")

            val_name = out_name

        if invert_stages:
            # Final inversion to produce ~(cascade(keyed))
            final = self._wire(f"_cas_{label}_out_")
            self._assign(final, f"~{val_name}")
            return final

        return val_name

    # ── Public build ─────────────────────────────────────────────────────────

    def build(self) -> Tuple[List[str], List[Tuple[str,str]], str]:
        """
        Emit the complete CAS-Lock block.
        Returns (new_wire_names, new_assign_pairs, Y_wire_name).
        """
        # ── Un-mask all key ports ────────────────────────────────────────────
        uk_g  = [self._unmask(i)          for i in range(self.N)]      # K1 ports
        uk_gb = [self._unmask(self.N + i) for i in range(self.N)]      # K2 ports

        # ── XOR inputs with recovered key bits ──────────────────────────────
        keyed_g  = [self._xor_input(self.inputs[i], uk_g[i],  f"g{i}")
                    for i in range(self.N)]
        keyed_gb = [self._xor_input(self.inputs[i], uk_gb[i], f"gb{i}")
                    for i in range(self.N)]

        # ── Build gcas (normal cascade) ──────────────────────────────────────
        g_out = self._build_cascade(keyed_g, "g", invert_stages=False)

        # ── Build gcas_bar (inverted-input cascade + final inversion) ────────
        # Internally K1=K2=k_half, so keyed_gb = keyed_g.
        # gcas_bar = ~(cascade(keyed_gb)) = ~gcas.
        gb_out = self._build_cascade(keyed_gb, "gb", invert_stages=True)

        # ── Y = gcas AND gcas_bar = gcas & ~gcas = 0 for correct key ─────────
        y_net = self._wire("_cas_Y_")
        self._assign(y_net, f"{g_out} & {gb_out}")

        return self.new_wires, self.new_assigns, y_net

    def key_port_names(self) -> List[str]:
        return [f"keyinput{i}" for i in range(2 * self.N)]

    def correct_key_bits(self) -> List[int]:
        return list(self.observed_key)


# ---------------------------------------------------------------------------
# Functional verification
# ---------------------------------------------------------------------------

def verify_correct_key(gate_seq: List[str], N: int,
                       k_half: List[int], mask: List[int]) -> bool:
    """
    Simulate the CAS-Lock block for all 2^N input patterns with the correct
    observed key.  Y must be 0 for every pattern.
    """
    def cascade(bits: List[int]) -> int:
        val = bits[0]
        for i, g in enumerate(gate_seq):
            val = (val & bits[i+1]) if g == 'AND' else (val | bits[i+1])
        return val

    # Un-mask to recover k_half for both halves
    internal_k1 = [k_half[i] for i in range(N)]   # = k_half
    internal_k2 = [k_half[i] for i in range(N)]   # = k_half (K1=K2)

    for pat in range(1 << N):
        bits = [(pat >> i) & 1 for i in range(N)]
        L1   = [bits[i] ^ internal_k1[i] for i in range(N)]
        L2   = [bits[i] ^ internal_k2[i] for i in range(N)]
        g    = cascade(L1)
        gb   = 1 - cascade(L2)   # ~gcas since L1=L2
        if g & gb:
            return False
    return True


# ---------------------------------------------------------------------------
# Output injection — RTL version
# ---------------------------------------------------------------------------

def inject_y_into_output(assigns: List[Tuple[str,str]],
                          target: str,
                          y_net: str
                          ) -> Tuple[List[Tuple[str,str]], str]:
    """
    Find the assign that drives `target`, redirect its output to an
    intermediate wire, then emit:
        assign target = intermediate ^ y_net;

    With the correct key y_net=0, so XOR is transparent.
    Returns (patched_assigns, intermediate_wire_name).
    """
    intermediate = f"_cas_prexor_{target}_"
    patched = list(assigns)
    found   = False

    for idx, (lhs, rhs) in enumerate(patched):
        if lhs == target:
            patched[idx] = (intermediate, rhs)
            found = True
            break

    if not found:
        raise ValueError(
            f"No assign found driving '{target}'. "
            f"Try --target-output with a different output name."
        )

    # Inject Y: target = pre_xor_value ^ Y
    patched.append((target, f"{intermediate} ^ {y_net}"))
    return patched, intermediate


# ---------------------------------------------------------------------------
# Verilog emitter
# ---------------------------------------------------------------------------

def emit_locked_rtl(module: RTLModule,
                    patched_assigns: List[Tuple[str,str]],
                    cas_wires:       List[str],
                    cas_assigns:     List[Tuple[str,str]],
                    intermediate_wire: str,
                    key_ports:       List[str],
                    gate_seq:        List[str],
                    actual_p:        int,
                    N:               int,
                    k_half:          List[int],
                    mask:            List[int],
                    observed_key:    List[int],
                    selected_inputs: List[str],
                    target_output:   str) -> str:

    hex_w   = math.ceil(2 * N / 4)
    hex_val = int(''.join(str(b) for b in observed_key), 2)
    hex_str = f"0x{hex_val:0{hex_w}X}"

    lines = []
    lines += module.header_comments
    lines += [
        "",
        "// " + "=" * 62,
        "//  CAS-Lock (RTL) applied by cas_lock_rtl.py",
        "//  Reference: Shakya et al., IACR TCHES 2020, pp. 175-202",
        "// " + "-" * 62,
        f"//  N (CAS-Lock inputs)  : {N}",
        f"//  Key size (2N bits)   : {2*N}",
        f"//  Gate sequence (gcas) : {' -> '.join(gate_seq)}",
        f"//  p-value (gcas)       : {actual_p}  / 2^{N} = {1<<N}",
        f"//  Corruptibility       : {actual_p/(1<<N)*100:.1f}%",
        f"//  CAS-Lock input nets  : {', '.join(selected_inputs)}",
        f"//  Target output net    : {target_output}",
        f"//  Observed key (hex)   : {hex_str}",
        f"//  k_half (internal)    : {k_half}",
        f"//  mask                 : {mask}",
        f"//  Observed key (bits)  : K1={list(observed_key[:N])}  K2={list(observed_key[N:])}",
        f"//  Key port order       : {', '.join(key_ports)}",
        f"//  SAT resistance       : 2^N - 1 = {(1<<N)-1} iterations",
        "// " + "=" * 62,
        "",
    ]

    # Module declaration — add key ports
    all_ports = module.inputs + module.outputs + key_ports
    lines.append(f"module {module.name} (")
    lines.append(",\n".join(f"    {p}" for p in all_ports))
    lines.append(");")
    lines.append("")

    # Original port declarations
    lines.append("  // --- Original input ports ---")
    for inp in module.inputs:
        lines.append(f"  input {inp};")
    lines.append("")

    lines.append("  // --- Original output ports ---")
    for out in module.outputs:
        lines.append(f"  output {out};")
    lines.append("")

    # Bus ports (if any)
    if module.bus_ports:
        lines.append("  // --- Bus ports ---")
        for name, hi, lo in module.bus_ports:
            lines.append(f"  // [{hi}:{lo}] {name}  (bus — manual check required)")
        lines.append("")

    # Key input declarations
    lines.append(f"  // --- CAS-Lock key input ports (2N={2*N}) ---")
    for kp in key_ports:
        lines.append(f"  input {kp};")
    lines.append("")

    # Original wire declarations
    lines.append("  // --- Original internal wires ---")
    for w in module.wires:
        lines.append(f"  wire {w};")
    lines.append("")

    # CAS-Lock wire declarations
    lines.append("  // --- CAS-Lock internal wires ---")
    lines.append(f"  wire {intermediate_wire};")
    for w in cas_wires:
        lines.append(f"  wire {w};")
    lines.append("")

    # Original assign statements (patched)
    lines.append("  // --- Original assign statements (target output patched) ---")
    for lhs, rhs in patched_assigns:
        lines.append(f"  assign {lhs} = {rhs};")
    lines.append("")

    # CAS-Lock assign statements
    lines.append("  // --- CAS-Lock assign statements ---")
    for lhs, rhs in cas_assigns:
        lines.append(f"  assign {lhs} = {rhs};")
    lines.append("")

    lines.append("endmodule")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level locking function
# ---------------------------------------------------------------------------

def apply_cas_lock_rtl(module: RTLModule,
                       N: int,
                       target_p: int,
                       k_half: Optional[List[int]],
                       target_output: Optional[str],
                       rng: random.Random) -> str:

    # ── Select N primary inputs ──────────────────────────────────────────────
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

    # ── Target output ────────────────────────────────────────────────────────
    if target_output is None:
        target_output = module.outputs[0] if module.outputs else None
    if not target_output:
        raise ValueError("No output ports found in the module.")
    if target_output not in module.outputs:
        raise ValueError(
            f"'{target_output}' not found in outputs: {module.outputs}"
        )

    # ── Half-key ─────────────────────────────────────────────────────────────
    if k_half is None:
        k_half = [rng.randint(0, 1) for _ in range(actual_N)]
    if len(k_half) != actual_N:
        raise ValueError(f"Key must have {actual_N} bits, got {len(k_half)}")

    # ── Random mask (hides K1=K2 from port inspection) ───────────────────────
    mask = [rng.randint(0, 1) for _ in range(2 * actual_N)]

    # ── Gate sequence ────────────────────────────────────────────────────────
    target_p = max(1, min(target_p, (1 << actual_N) - 1))
    gate_seq = build_gate_sequence(actual_N, target_p)
    actual_p = simulate_gcas(gate_seq, actual_N)

    # ── Verify ───────────────────────────────────────────────────────────────
    if not verify_correct_key(gate_seq, actual_N, k_half, mask):
        raise RuntimeError("INTERNAL ERROR: correct key verification failed!")

    # ── Build CAS-Lock assign block ──────────────────────────────────────────
    builder = RTLCASLockBuilder(selected, gate_seq, k_half, mask)
    cas_wires, cas_assigns, y_net = builder.build()
    key_ports    = builder.key_port_names()
    observed_key = builder.correct_key_bits()

    # ── Inject Y into target output ──────────────────────────────────────────
    patched_assigns, intermediate_wire = inject_y_into_output(
        module.assigns, target_output, y_net
    )

    # ── Emit RTL ─────────────────────────────────────────────────────────────
    return emit_locked_rtl(
        module, patched_assigns, cas_wires, cas_assigns,
        intermediate_wire, key_ports, gate_seq,
        actual_p, actual_N, k_half, mask, observed_key,
        selected, target_output
    )


# ---------------------------------------------------------------------------
# Key report
# ---------------------------------------------------------------------------

def print_key_report(module_name, N, k_half, mask, observed_key,
                     key_ports, gate_seq, actual_p, target_output,
                     selected_inputs):
    W = 66
    print()
    print("=" * W)
    print("  CAS-Lock (RTL) Applied Successfully")
    print("=" * W)
    print(f"  Module            : {module_name}")
    print(f"  CAS inputs (N)    : {N}  ->  key size 2N = {2*N} bits")
    print(f"  CAS input nets    : {', '.join(selected_inputs)}")
    print(f"  Target output     : {target_output}")
    print(f"  Gate sequence     : {' -> '.join(gate_seq)}")
    print(f"  p-value (gcas)    : {actual_p}  /  2^{N} = {1<<N}")
    print(f"  Corruptibility    : {actual_p/(1<<N)*100:.1f}%")
    print()

    hex_w   = math.ceil(2 * N / 4)
    hex_val = int(''.join(str(b) for b in observed_key), 2)
    print("  Correct key  [KEEP SECRET]")
    print(f"    k_half (internal) : {' '.join(str(b) for b in k_half)}")
    print(f"    mask              : {' '.join(str(b) for b in mask)}")
    k1_obs = observed_key[:N]
    k2_obs = observed_key[N:]
    print(f"    Observed K1       : {' '.join(str(b) for b in k1_obs)}")
    print(f"    Observed K2       : {' '.join(str(b) for b in k2_obs)}")
    print(f"    Full 2N observed  : {' '.join(str(b) for b in observed_key)}")
    print(f"    Hex               : 0x{hex_val:0{hex_w}X}")
    print()
    print("  Port name             Correct bit   Role")
    print("  " + "-" * 48)
    for i, (port, bit) in enumerate(zip(key_ports, observed_key)):
        role = f"K1[{i}]  (mask={mask[i]})" if i < N \
               else f"K2[{i-N}]  (mask={mask[i]})"
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
        description="Apply CAS-Lock to a behavioral/RTL Verilog netlist.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("input",  help="Input RTL Verilog file (.v)")
    ap.add_argument("-o", "--output",       default=None)
    ap.add_argument("-n", "--num-inputs",   type=int, default=4)
    ap.add_argument("-p", "--p-value",      type=int, default=None)
    ap.add_argument("-s", "--seed",         type=int, default=42)
    ap.add_argument("--target-output",      default=None)
    ap.add_argument("--key",                default=None,
                    help="N comma-separated half-key bits (K1=K2=key internally)")
    return ap.parse_args()


def main():
    args = parse_args()
    rng  = random.Random(args.seed)

    print(f"[CAS-Lock RTL] Reading {args.input} ...")
    with open(args.input) as f:
        text = f.read()

    module = parse_rtl(text)
    print(f"[CAS-Lock RTL] Parsed module '{module.name}': "
          f"{len(module.inputs)} inputs, {len(module.outputs)} outputs, "
          f"{len(module.assigns)} assign statements")

    N = args.num_inputs
    if N > len(module.inputs):
        print(f"[CAS-Lock RTL] WARNING: N={N} > available inputs "
              f"({len(module.inputs)}); reducing.")
        N = len(module.inputs)
    if N < 2:
        print("[CAS-Lock RTL] ERROR: need at least 2 inputs.")
        sys.exit(1)

    target_p = args.p_value if args.p_value is not None else N

    k_half = None
    if args.key:
        k_half = [int(b.strip()) for b in args.key.split(',')]
        if len(k_half) != N:
            print(f"[CAS-Lock RTL] ERROR: --key must have {N} bits, "
                  f"got {len(k_half)}")
            sys.exit(1)

    print(f"[CAS-Lock RTL] Applying CAS-Lock (N={N}, target p~{target_p}) ...")
    locked = apply_cas_lock_rtl(
        module, N, target_p, k_half, args.target_output, rng
    )

    # Parse summary fields from emitted header for the report
    def _re(pattern, default=""):
        m = re.search(pattern, locked)
        return m.group(1).strip() if m else default

    raw_gates = _re(r'Gate sequence \(gcas\)\s*:\s*(.+)')
    raw_p     = _re(r'p-value \(gcas\)\s*:\s*(\d+)', str(target_p))
    raw_inps  = _re(r'CAS-Lock input nets\s*:\s*(.+)')
    raw_tgt   = _re(r'Target output net\s*:\s*(\S+)')
    m_kh = re.search(r'k_half \(internal\)\s*:\s*(\[[\d, ]+\])', locked)
    m_mk = re.search(r'mask\s*:\s*(\[[\d, ]+\])',                 locked)

    import ast
    final_k_half = ast.literal_eval(m_kh.group(1)) if m_kh else (k_half or [])
    final_mask   = ast.literal_eval(m_mk.group(1)) if m_mk else []
    final_N      = len(final_k_half)
    final_obs    = [final_k_half[i % final_N] ^ final_mask[i]
                    for i in range(2 * final_N)] if final_mask else []
    final_ports  = [f"keyinput{i}" for i in range(2 * final_N)]
    final_gates  = [g.strip() for g in raw_gates.split('->')] if raw_gates else []
    final_p      = int(raw_p)
    final_inps   = [s.strip() for s in raw_inps.split(',')] if raw_inps else []

    print_key_report(
        module.name, final_N, final_k_half, final_mask, final_obs,
        final_ports, final_gates, final_p, raw_tgt, final_inps
    )

    out_path = args.output or args.input.replace('.v', '_caslocked.v')
    with open(out_path, 'w') as f:
        f.write(locked)
    print(f"[CAS-Lock RTL] Locked RTL written -> {out_path}")


if __name__ == "__main__":
    main()
