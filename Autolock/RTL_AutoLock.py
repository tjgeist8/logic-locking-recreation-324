"""
AutoLock Unified — Logic Locking via Genetic Algorithm
Supports BOTH:
  1. Gate-instantiation netlists  (xor g1 (.a(a), .b(b), .out(w1));)
  2. RTL assign-based netlists    (assign new_n44 = ~G1GAT;)

Output: locked Verilog + key file. Feed the .v to your own bench converter.

Usage:
    python autolock_unified.py [verilog_file] [options]
    python autolock_unified.py c432.v
    python autolock_unified.py c432.v --key-length 16 --generations 30
    python autolock_unified.py --help
"""

import random
import copy
import sys
import re
import argparse
from collections import defaultdict

try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


# ─────────────────────────────────────────────
# GLOBAL DEFAULTS (overridden by CLI args)
# ─────────────────────────────────────────────

POPULATION_SIZE   = 10
NUM_GENERATIONS   = 50
MUTATION_RATE     = 0.15
CROSSOVER_RATE    = 0.7
KEY_LENGTH        = 64

_ATTACK_TRIALS_GA    = 5
_ATTACK_TRIALS_FINAL = 30

OUTPUT_PORTS = {'ZN', 'Z', 'Y', 'Q', 'QN', 'out', 'y', 'q', 'z', 'o', 'sum', 'cout'}
CLOCK_PORTS  = {'CK', 'CLK', 'clock', 'clk', 'SE', 'SI', 'CDN', 'SDN'}
RESERVED_NETS = {'clock', 'clk', 'reset', 'rst', 'vdd', 'gnd'}
CONSTANT_RE = re.compile(r"\d+'[bhdBHD][0-9a-fA-FxXzZ_]+")

SAMPLE_VERILOG = """
module simple_adder (
    input  wire a, b, cin,
    output wire sum, cout
);
    wire w1, w2, w3;
    xor g1 (.a(a),  .b(b),   .out(w1));
    xor g2 (.a(w1), .b(cin), .out(sum));
    and g3 (.a(a),  .b(b),   .out(w2));
    and g4 (.a(w1), .b(cin), .out(w3));
    or  g5 (.a(w2), .b(w3),  .out(cout));
endmodule
"""

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def is_constant(signal: str) -> bool:
    return bool(CONSTANT_RE.fullmatch(signal.strip()))

def strip_comments(text: str) -> str:
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    return text


# ─────────────────────────────────────────────
# NETLIST TYPE DETECTION
# ─────────────────────────────────────────────

def detect_netlist_type(source: str) -> str:
    """
    Returns 'assign' if the module is primarily assign-based RTL,
    or 'gate' if it uses gate instantiation.
    """
    src = strip_comments(source)
    assign_count = len(re.findall(r'\bassign\b', src))
    # Count gate instantiations (lines with .port(net) pattern but not module header)
    gate_count = len(re.findall(r'\.\w+\s*\(\s*\w+\s*\)', src))
    # Rough heuristic: if many assigns and few relative gate instances
    if assign_count > 5 and assign_count * 2 > gate_count:
        return 'assign'
    return 'gate'


# ─────────────────────────────────────────────
# 1. VERILOG PARSER — ASSIGN (RTL) MODE
# ─────────────────────────────────────────────
#
# Handles:
#   assign out = ~in;                    -> NOT
#   assign out = a & b & c;             -> AND (multi-input)
#   assign out = a | b;                 -> OR
#   assign out = a ^ b;                 -> XOR
#   assign out = ~(a & b);             -> NAND
#   assign out = ~(a | b);             -> NOR
#   assign out = ~(a ^ b);             -> XNOR
#   assign out = a ? b : c;            -> MUX
#   assign out = a;                     -> BUFF

def parse_assign_expr(lhs: str, rhs: str, gate_idx: int) -> list:
    """
    Parse one assign statement into a list of gate dicts.
    May produce multiple gates for complex expressions.
    Returns list of gate dicts with keys: name, type, ports.
    """
    rhs = rhs.strip().rstrip(';')
    gates = []

    # Ternary / MUX:  sel ? a : b
    m = re.match(r'^(\w+)\s*\?\s*(\w+)\s*:\s*(\w+)$', rhs)
    if m:
        sel, a, b = m.group(1), m.group(2), m.group(3)
        gates.append({
            'name': f'g{gate_idx}',
            'type': 'MUX2',
            'ports': {'sel': sel, 'in1': a, 'in0': b, 'out': lhs},
        })
        return gates

    # NOT: ~x  or  !x
    m = re.match(r'^[~!]\s*(\w+)$', rhs)
    if m:
        gates.append({
            'name': f'g{gate_idx}',
            'type': 'NOT',
            'ports': {'a': m.group(1), 'ZN': lhs},
        })
        return gates

    # NAND: ~(a & b & ...)
    m = re.match(r'^[~!]\s*\((.+)\)$', rhs)
    if m:
        inner = m.group(1).strip()
        if '&' in inner and '|' not in inner and '^' not in inner:
            inputs = [t.strip() for t in inner.split('&')]
            ports = {f'a{i}': v for i, v in enumerate(inputs)}
            ports['ZN'] = lhs
            gates.append({'name': f'g{gate_idx}', 'type': 'NAND', 'ports': ports})
            return gates
        if '|' in inner and '&' not in inner and '^' not in inner:
            inputs = [t.strip() for t in inner.split('|')]
            ports = {f'a{i}': v for i, v in enumerate(inputs)}
            ports['ZN'] = lhs
            gates.append({'name': f'g{gate_idx}', 'type': 'NOR', 'ports': ports})
            return gates
        if '^' in inner and '&' not in inner and '|' not in inner:
            inputs = [t.strip() for t in inner.split('^')]
            ports = {f'a{i}': v for i, v in enumerate(inputs)}
            ports['ZN'] = lhs
            gates.append({'name': f'g{gate_idx}', 'type': 'XNOR', 'ports': ports})
            return gates

    # AND: a & b & ...
    if '&' in rhs and '|' not in rhs and '^' not in rhs and '~' not in rhs and '!' not in rhs:
        inputs = [t.strip() for t in rhs.split('&')]
        if all(re.match(r'^\w+$', t) for t in inputs):
            ports = {f'a{i}': v for i, v in enumerate(inputs)}
            ports['ZN'] = lhs
            gates.append({'name': f'g{gate_idx}', 'type': 'AND', 'ports': ports})
            return gates

    # OR: a | b | ...
    if '|' in rhs and '&' not in rhs and '^' not in rhs and '~' not in rhs and '!' not in rhs:
        inputs = [t.strip() for t in rhs.split('|')]
        if all(re.match(r'^\w+$', t) for t in inputs):
            ports = {f'a{i}': v for i, v in enumerate(inputs)}
            ports['ZN'] = lhs
            gates.append({'name': f'g{gate_idx}', 'type': 'OR', 'ports': ports})
            return gates

    # XOR: a ^ b
    if '^' in rhs and '&' not in rhs and '|' not in rhs and '~' not in rhs and '!' not in rhs:
        inputs = [t.strip() for t in rhs.split('^')]
        if all(re.match(r'^\w+$', t) for t in inputs):
            ports = {f'a{i}': v for i, v in enumerate(inputs)}
            ports['ZN'] = lhs
            gates.append({'name': f'g{gate_idx}', 'type': 'XOR', 'ports': ports})
            return gates

    # BUFF: simple wire assignment
    m = re.match(r'^(\w+)$', rhs)
    if m:
        gates.append({
            'name': f'g{gate_idx}',
            'type': 'BUFF',
            'ports': {'a': m.group(1), 'ZN': lhs},
        })
        return gates

    # Complex expression — decompose into NOT + AND/OR using intermediate wires
    # Strategy: if it starts with ~( ... op ... ), handle NAND/NOR via inner parse
    # Fallback: create a "LOGIC" pseudo-gate capturing all signal references
    all_nets = re.findall(r'\b([A-Za-z_]\w*)\b', rhs)
    all_nets = [n for n in all_nets if not is_constant(n)]
    if all_nets:
        ports = {f'a{i}': v for i, v in enumerate(all_nets)}
        ports['ZN'] = lhs
        gates.append({'name': f'g{gate_idx}', 'type': 'LOGIC', 'ports': ports})
    return gates


def parse_verilog_assign(source: str) -> dict:
    """Parse RTL Verilog with assign statements."""
    src = strip_comments(source)
    netlist = {'module': '', 'inputs': [], 'outputs': [], 'wires': [], 'gates': [], '_mode': 'assign'}

    m = re.search(r'\bmodule\s+(\w+)', src)
    if m:
        netlist['module'] = m.group(1)

    port_pattern = re.compile(
        r'\b(input|output)\b\s+(?:wire\s+)?(?:reg\s+)?'
        r'(?:\[(\d+):(\d+)\]\s+)?([\w\s,]+);'
    )
    for direction, hi, lo, nets in port_pattern.findall(src):
        names = [n.strip() for n in nets.split(',') if n.strip()]
        if hi != '' and lo != '':
            hi_i, lo_i = int(hi), int(lo)
            for name in names:
                for i in range(lo_i, hi_i + 1):
                    netlist[direction + 's'].append(f"{name}[{i}]")
        else:
            netlist[direction + 's'].extend(names)

    # Scalar wires
    for net in re.findall(r'\bwire\b\s+([\w\s,]+);', src):
        if '[' in net:
            continue
        names = [n.strip() for n in net.split(',') if n.strip()]
        netlist['wires'].extend(names)

    # Bus wires
    for match in re.finditer(r'\bwire\b\s*\[(\d+):(\d+)\]\s+([\w]+)\s*;', src):
        hi, lo, base = int(match.group(1)), int(match.group(2)), match.group(3)
        for i in range(lo, hi + 1):
            netlist['wires'].append(f"{base}[{i}]")

    # Parse assign statements
    assign_re = re.compile(r'\bassign\s+(\w+)\s*=\s*([^;]+);', re.DOTALL)
    gate_idx = 0
    for m in assign_re.finditer(src):
        lhs = m.group(1).strip()
        rhs = m.group(2).strip()
        parsed = parse_assign_expr(lhs, rhs, gate_idx)
        netlist['gates'].extend(parsed)
        gate_idx += len(parsed) if parsed else 1

    return netlist


# ─────────────────────────────────────────────
# 2. VERILOG PARSER — GATE INSTANTIATION MODE
# ─────────────────────────────────────────────

def parse_verilog_gate(source: str) -> dict:
    """Parse gate-instantiation Verilog."""
    src = strip_comments(source)
    netlist = {'module': '', 'inputs': [], 'outputs': [], 'wires': [], 'gates': [], '_mode': 'gate'}

    m = re.search(r'\bmodule\s+(\w+)', src)
    if m:
        netlist['module'] = m.group(1)

    port_pattern = re.compile(
        r'\b(input|output)\b\s+(?:wire\s+)?(?:\[(\d+):(\d+)\]\s+)?([\w\s,]+);'
    )
    for direction, hi, lo, nets in port_pattern.findall(src):
        names = [n.strip() for n in nets.split(',') if n.strip()]
        if hi != '' and lo != '':
            hi_i, lo_i = int(hi), int(lo)
            for name in names:
                for i in range(lo_i, hi_i + 1):
                    netlist[direction + 's'].append(f"{name}[{i}]")
        else:
            netlist[direction + 's'].extend(names)

    for net in re.findall(r'\bwire\b\s+([\w\s,]+);', src):
        if '[' in net:
            continue
        names = [n.strip() for n in net.split(',') if n.strip()]
        netlist['wires'].extend(names)

    for match in re.finditer(r'\bwire\b\s*\[(\d+):(\d+)\]\s+([\w]+)\s*;', src):
        hi, lo, base = int(match.group(1)), int(match.group(2)), match.group(3)
        for i in range(lo, hi + 1):
            netlist['wires'].append(f"{base}[{i}]")

    SKIP_KEYWORDS = {
        'module', 'endmodule', 'input', 'output', 'inout', 'wire', 'reg',
        'assign', 'always', 'begin', 'end', 'if', 'else', 'case', 'endcase',
        'for', 'while', 'posedge', 'negedge', 'parameter', 'localparam',
        'integer', 'genvar', 'generate', 'endgenerate',
    }

    gate_pattern = re.compile(r'(?<![.\w])([A-Za-z]\w*)\s+(\w+)\s*\(([^;]*?)\)\s*;', re.DOTALL)
    for gtype, gname, port_body in gate_pattern.findall(src):
        if gtype.lower() in SKIP_KEYWORDS or gname.lower() in SKIP_KEYWORDS:
            continue
        ports = {}
        for pm in re.finditer(r'\.(\w+)\s*\(\s*([^)]+?)\s*\)', port_body):
            ports[pm.group(1)] = pm.group(2).strip()
        if not ports:
            continue
        netlist['gates'].append({'name': gname, 'type': gtype, 'ports': ports})

    return netlist


# ─────────────────────────────────────────────
# 3. UNIFIED PARSER
# ─────────────────────────────────────────────

def parse_verilog(source: str) -> dict:
    mode = detect_netlist_type(source)
    print(f"Detected netlist mode: {mode.upper()}")
    if mode == 'assign':
        return parse_verilog_assign(source)
    else:
        return parse_verilog_gate(source)


# ─────────────────────────────────────────────
# 4. GRAPH BUILDER
# ─────────────────────────────────────────────

def _get_gate_io(gate: dict, mode: str):
    """Return (output_nets, input_nets) for a gate dict."""
    ports = gate['ports']
    gtype = gate['type'].upper()

    if mode == 'assign':
        # For assign-parsed gates, ZN / out is the output; everything else is input
        out_keys = {'ZN', 'out', 'Z', 'Y', 'Q'}
        out_nets = [v for k, v in ports.items() if k in out_keys]
        in_nets  = [v for k, v in ports.items() if k not in out_keys and k not in CLOCK_PORTS]
        return out_nets, in_nets

    else:  # gate mode
        out_ports = [p for p in ports if p in OUTPUT_PORTS]
        in_ports  = [p for p in ports if p not in OUTPUT_PORTS and p not in CLOCK_PORTS]
        if not out_ports and ports:
            pl = list(ports.keys())
            out_ports = [pl[-1]]
            in_ports  = pl[:-1]
        return [ports[p] for p in out_ports], [ports[p] for p in in_ports]


def build_graph(netlist: dict):
    mode  = netlist.get('_mode', 'gate')
    all_nets = set(netlist['inputs'] + netlist['outputs'] + netlist['wires'])
    graph = defaultdict(lambda: {'fanout': [], 'fanin': []})

    for gate in netlist['gates']:
        out_nets, in_nets = _get_gate_io(gate, mode)

        for driver in out_nets:
            all_nets.add(driver)
            for sink in in_nets:
                if is_constant(sink):
                    continue
                all_nets.add(sink)
                graph[sink]['fanout'].append(driver)
                graph[driver]['fanin'].append(sink)

    return dict(graph), list(all_nets)


# ─────────────────────────────────────────────
# 5. DESCENDANT CHECK
# ─────────────────────────────────────────────

def is_descendant(graph, start_node, target_node):
    if start_node == target_node:
        return True
    visited = set()
    queue = [start_node]
    while queue:
        curr = queue.pop(0)
        if curr == target_node:
            return True
        if curr not in visited:
            visited.add(curr)
            for child in graph.get(curr, {}).get('fanout', []):
                queue.append(child)
    return False


# ─────────────────────────────────────────────
# 6. INITIAL POPULATION
# ─────────────────────────────────────────────

def generate_initial_population(netlist, graph, nodes, key_length, pop_size):
    mode = netlist.get('_mode', 'gate')
    candidates = []

    for gi, gate in enumerate(netlist['gates']):
        ports = gate['ports']
        out_nets, in_nets_keys = _get_gate_io_keys(gate, mode)
        for port_key in in_nets_keys:
            signal = ports.get(port_key, '')
            if not signal:
                continue
            if signal in RESERVED_NETS:
                continue
            if signal in netlist['inputs']:
                continue
            if is_constant(signal):
                continue
            candidates.append((gi, port_key, signal))

    if not candidates:
        raise RuntimeError("No valid locking candidates found.")

    population = []
    for _ in range(pop_size):
        individual = []


        chosen_points = random.sample(candidates, key_length)

        for gi, port, signal in chosen_points:
            fake_signal = random.choice(nodes)
            attempts = 0
            while (fake_signal == signal or
                   is_constant(fake_signal) or
                   is_descendant(graph, signal, fake_signal)):
                fake_signal = random.choice(nodes)
                attempts += 1
                if attempts > 100: break # Failsafe just in case

            key_bit = random.randint(0, 1)
            individual.append((gi, port, signal, fake_signal, key_bit))



        population.append(individual)

    return population


def _get_gate_io_keys(gate, mode):
    """Return (output_port_keys, input_port_keys) — returns key names, not values."""
    ports = gate['ports']
    gtype = gate['type'].upper()

    if mode == 'assign':
        out_keys = {'ZN', 'out', 'Z', 'Y', 'Q'}
        o = [k for k in ports if k in out_keys]
        i = [k for k in ports if k not in out_keys and k not in CLOCK_PORTS]
        return o, i
    else:
        out_keys = [p for p in ports if p in OUTPUT_PORTS]
        in_keys  = [p for p in ports if p not in OUTPUT_PORTS and p not in CLOCK_PORTS]
        if not out_keys and ports:
            pl = list(ports.keys())
            out_keys = [pl[-1]]
            in_keys  = pl[:-1]
        return out_keys, in_keys


# ─────────────────────────────────────────────
# 7. APPLY LOCKING
# ─────────────────────────────────────────────

def apply_locking(netlist: dict, individual: list):
    locked = copy.deepcopy(netlist)
    locked['locking_points'] = []
    locked['key'] = []
    added_wires = []

    for idx, (gi, port, signal, fake_signal, key_bit) in enumerate(individual):
        mux_out = f"lock_net_{idx}"
        added_wires.append(mux_out)

        gate = locked['gates'][gi]
        gate['ports'][port] = mux_out

        if key_bit == 1:
            in1_val, in0_val = signal, fake_signal
        else:
            in1_val, in0_val = fake_signal, signal

        locked['locking_points'].append({
            'mux': f"KEY_MUX_{idx}",
            'in0': in0_val,
            'in1': in1_val,
            'sel': f"keyinput[{idx}]",
            'out': mux_out,
        })
        locked['key'].append(key_bit)

    locked['wires'].extend(added_wires)
    return locked


# ─────────────────────────────────────────────
# 8. ATTACK MODEL
# ─────────────────────────────────────────────

def simulate_attack_once(individual, graph, nodes):
    if not nodes:
        return 0.5

    adj = defaultdict(set)
    for node, info in graph.items():
        for nb in info.get('fanout', []):
            adj[node].add(nb); adj[nb].add(node)
        for nb in info.get('fanin', []):
            adj[node].add(nb); adj[nb].add(node)

    def bfs_distance(src, dst):
        if src == dst:
            return 0
        visited = {src}
        queue = [(src, 0)]
        while queue:
            curr, dist = queue.pop(0)
            for nb in adj.get(curr, set()):
                if nb == dst:
                    return dist + 1
                if nb not in visited:
                    visited.add(nb); queue.append((nb, dist + 1))
        return 999

    def degree(node):
        return (len(graph.get(node, {}).get('fanout', [])) +
                len(graph.get(node, {}).get('fanin',  [])))

    correct_guesses = 0
    for (gi, port, signal, fake_signal, key_bit) in individual:
        dist = bfs_distance(signal, fake_signal)
        score_signal = degree(signal)      / (1.0 + dist * 0.1)
        score_fake   = degree(fake_signal) / (1.0 + dist * 0.1)
        noise = random.gauss(0, 0.05)
        attacker_guess = 1 if (score_signal + noise) >= score_fake else 0
        if attacker_guess == key_bit:
            correct_guesses += 1

    return correct_guesses / len(individual) if individual else 0.5


def simulate_attack(individual, graph, nodes, n_trials=_ATTACK_TRIALS_GA):
    return sum(simulate_attack_once(individual, graph, nodes) for _ in range(n_trials)) / n_trials


def compute_fitness(individual, graph, nodes, n_trials=_ATTACK_TRIALS_GA):
    return 1.0 - simulate_attack(individual, graph, nodes, n_trials)


# ─────────────────────────────────────────────
# 9. SELECTION / CROSSOVER / MUTATION
# ─────────────────────────────────────────────

def select_parents(population, fitnesses, n_parents):
    TOURNAMENT_SIZE = 3
    parents = []
    indexed = list(zip(fitnesses, population))
    for _ in range(n_parents):
        contestants = random.sample(indexed, min(TOURNAMENT_SIZE, len(indexed)))
        parents.append(max(contestants, key=lambda x: x[0])[1])
    return parents


def crossover(parent_a, parent_b):
    if len(parent_a) <= 1:
        return copy.deepcopy(parent_a), copy.deepcopy(parent_b)
    cut = random.randint(1, len(parent_a) - 1)
    return parent_a[:cut] + parent_b[cut:], parent_b[:cut] + parent_a[cut:]


def mutate(individual, netlist, graph, nodes, mutation_rate):
    mutated = copy.deepcopy(individual)
    for i, (gi, port, signal, fake_signal, key_bit) in enumerate(mutated):
        if random.random() < mutation_rate:
            if random.randint(0, 1) == 0:
                attempts = 0
                new_fake = random.choice(nodes)
                while (new_fake == signal or is_constant(new_fake) or
                       is_descendant(graph, signal, new_fake)):
                    new_fake = random.choice(nodes)
                    attempts += 1
                    if attempts > 200:
                        break
                fake_signal = new_fake
            else:
                key_bit ^= 1
            mutated[i] = (gi, port, signal, fake_signal, key_bit)
    return mutated


# ─────────────────────────────────────────────
# 10. GENETIC ALGORITHM
# ─────────────────────────────────────────────

def run_genetic_algorithm(netlist, graph, nodes, pop_size, num_gen, key_len,
                           mutation_rate, crossover_rate):
    print(f"\n{'='*60}")
    print(f"  AutoLock GA  |  Pop={pop_size}  Gen={num_gen}  Key={key_len}")
    print(f"  Mode: {netlist.get('_mode','gate').upper()}")
    print(f"{'='*60}\n")

    population = generate_initial_population(netlist, graph, nodes, key_len, pop_size)
    history = []
    best_individual  = None
    best_fitness_seen = -1.0

    for gen in range(num_gen):
        fitnesses = [compute_fitness(ind, graph, nodes) for ind in population]
        gen_best = max(fitnesses)
        gen_avg  = sum(fitnesses) / len(fitnesses)
        history.append((gen_best, gen_avg))
        best_idx = fitnesses.index(gen_best)

        if gen_best > best_fitness_seen:
            best_fitness_seen = gen_best
            best_individual   = copy.deepcopy(population[best_idx])

        if (gen + 1) % 10 == 0 or gen == 0:
            print(f"Gen {gen+1:>3}/{num_gen} | Best: {gen_best:.4f} | Avg: {gen_avg:.4f}")

        parents = select_parents(population, fitnesses, pop_size)
        new_population = [copy.deepcopy(population[best_idx])]

        while len(new_population) < pop_size:
            pa, pb = random.sample(parents, 2)
            if random.random() < crossover_rate:
                child_a, child_b = crossover(pa, pb)
            else:
                child_a, child_b = copy.deepcopy(pa), copy.deepcopy(pb)
            child_a = mutate(child_a, netlist, graph, nodes, mutation_rate)
            child_b = mutate(child_b, netlist, graph, nodes, mutation_rate)
            new_population.append(child_a)
            if len(new_population) < pop_size:
                new_population.append(child_b)
        population = new_population

    print(f"\nRe-evaluating champion over {_ATTACK_TRIALS_FINAL} trials...")
    best_fitness_final = compute_fitness(best_individual, graph, nodes, n_trials=_ATTACK_TRIALS_FINAL)
    return best_individual, best_fitness_final, history


# ─────────────────────────────────────────────
# 11. VERILOG OUTPUT — ASSIGN MODE
# ─────────────────────────────────────────────

def format_locked_verilog_assign(netlist, locked):
    """
    Reconstruct a locked Verilog file from an assign-mode netlist.
    Each gate dict is turned back into an assign statement.
    Locking MUXes are inserted as additional assign statements.
    """
    key  = locked.get('key', [])
    lps  = locked.get('locking_points', [])
    mod  = netlist.get('module', 'locked_circuit')
    lines = []

    lines.append("// AutoLock-generated locked netlist (assign/RTL mode)")
    lines.append(f"// Correct key: {key}")
    lines.append(f"module {mod}_locked (")
    lines.append(f"(* keep = 1 *)    input wire [{len(key)-1}:0] keyinput,")
    if netlist['inputs']:
        lines.append("    input wire " + ", ".join(netlist['inputs']) + ",")
    if netlist['outputs']:
        lines.append("    output wire " + ", ".join(netlist['outputs']))
    lines.append(");")
    lines.append("")

    # Wire declarations
    wire_list = list(dict.fromkeys(
        w for w in locked['wires'] if w not in netlist['outputs']
    ))
    if wire_list:
        # Chunk into groups of 8 for readability
        for i in range(0, len(wire_list), 8):
            chunk = wire_list[i:i+8]
            lines.append("    wire " + ", ".join(chunk) + ";")
    lines.append("")

    # Recreate assign statements from gate dicts
    lines.append("    // Original logic (reconstruct assign statements)")

    def gate_to_assign(gate):
        gtype = gate['type'].upper()
        ports = gate['ports']
        out_keys = {'ZN', 'out', 'Z', 'Y', 'Q'}
        lhs = next((v for k, v in ports.items() if k in out_keys), None)
        if lhs is None:
            return None
        ins = [v for k, v in ports.items() if k not in out_keys and k not in CLOCK_PORTS]

        if gtype == 'NOT':
            return f"    assign {lhs} = ~{ins[0]};" if ins else None
        elif gtype == 'BUFF':
            return f"    assign {lhs} = {ins[0]};" if ins else None
        elif gtype == 'AND':
            return f"    assign {lhs} = {' & '.join(ins)};" if ins else None
        elif gtype == 'OR':
            return f"    assign {lhs} = {' | '.join(ins)};" if ins else None
        elif gtype == 'XOR':
            return f"    assign {lhs} = {' ^ '.join(ins)};" if ins else None
        elif gtype == 'NAND':
            return f"    assign {lhs} = ~({' & '.join(ins)});" if ins else None
        elif gtype == 'NOR':
            return f"    assign {lhs} = ~({' | '.join(ins)});" if ins else None
        elif gtype == 'XNOR':
            return f"    assign {lhs} = ~({' ^ '.join(ins)});" if ins else None
        elif gtype == 'MUX2':
            sel  = ports.get('sel', ins[0] if ins else '1b0')
            in1  = ports.get('in1', ins[1] if len(ins) > 1 else '1b0')
            in0  = ports.get('in0', ins[2] if len(ins) > 2 else '1b0')
            return f"    assign {lhs} = {sel} ? {in1} : {in0};"
        elif gtype == 'LOGIC':
            # Reproduce as a comment; we can't reconstruct arbitrary logic
            return f"    // LOGIC gate {gate['name']}: out={lhs} (complex expr — manual review needed)"
        else:
            return f"    // Unknown gate type {gtype} for {lhs}"

    for gate in locked['gates']:
        stmt = gate_to_assign(gate)
        if stmt:
            lines.append(stmt)

    lines.append("")
    lines.append("    // Locking MUXes: out = sel ? in1 : in0")
    for lp in lps:
        lines.append(
            f"    assign {lp['out']} = {lp['sel']} ? {lp['in1']} : {lp['in0']};"
        )

    lines.append("")
    lines.append("endmodule")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# 12. VERILOG OUTPUT — GATE MODE
# ─────────────────────────────────────────────

def format_locked_verilog_gate(netlist, locked):
    key  = locked.get('key', [])
    lps  = locked.get('locking_points', [])
    mod  = netlist.get('module', 'locked_circuit')
    lines = []

    lines.append("// AutoLock-generated locked netlist (gate-instantiation mode)")
    lines.append(f"// Correct key: {key}")
    lines.append(f"module {mod}_locked (")
    lines.append(f"    input wire [{len(key)-1}:0] key,")
    if netlist['inputs']:
        lines.append("    input wire " + ", ".join(netlist['inputs']) + ",")
    if netlist['outputs']:
        lines.append("    output wire " + ", ".join(netlist['outputs']))
    lines.append(");")
    lines.append("")

    wire_list = list(dict.fromkeys(
        w for w in locked['wires'] if w not in netlist['outputs']
    ))
    if wire_list:
        lines.append("    wire " + ", ".join(wire_list) + ";")
    lines.append("")

    lines.append("    // Original gates")
    for g in locked['gates']:
        port_str = ", ".join(f".{p}({n})" for p, n in g['ports'].items())
        lines.append(f"    {g['type']} {g['name']} ({port_str});")

    lines.append("")
    lines.append("    // Locking MUXes")
    for lp in lps:
        lines.append(
            f"    mux2 {lp['mux']} (.in0({lp['in0']}), .in1({lp['in1']}), "
            f".sel({lp['sel']}), .out({lp['out']}));"
        )

    lines.append("")
    lines.append("endmodule")
    return "\n".join(lines)


def format_locked_verilog(netlist, locked):
    mode = netlist.get('_mode', 'gate')
    if mode == 'assign':
        return format_locked_verilog_assign(netlist, locked)
    else:
        return format_locked_verilog_gate(netlist, locked)


# ─────────────────────────────────────────────
# 13. RESULTS & OUTPUT
# ─────────────────────────────────────────────

def print_results(netlist, best_individual, best_fitness):
    locked     = apply_locking(netlist, best_individual)
    key        = locked['key']
    attack_acc = 1.0 - best_fitness

    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    print(f"Best Fitness    : {best_fitness:.4f}")
    print(f"Attack Accuracy : {attack_acc:.4f}  (random baseline = 0.5000)")
    print(f"Key Length      : {len(key)} bits")
    print(f"Correct Key     : {''.join(str(b) for b in key)}")
    print()

    return format_locked_verilog(netlist, locked), key


def save_outputs(verilog_out, key, history, base_name="best"):
    v_file = f"{base_name}_locked_verilog.v"
    k_file = f"{base_name}_verilog_key.txt"

    with open(v_file, "w") as f:
        f.write(verilog_out)
    print(f"Saved: {v_file}")

    with open(k_file, "w") as f:
        f.write("Correct key (binary): " + ''.join(str(b) for b in key) + "\n")
        f.write("Key bits: " + str(key) + "\n")
    print(f"Saved: {k_file}")

    if HAS_MATPLOTLIB and history:
        gens  = range(1, len(history) + 1)
        bests = [h[0] for h in history]
        avgs  = [h[1] for h in history]
        plt.figure(figsize=(9, 4))
        plt.plot(gens, bests, linewidth=2, label='Best Fitness')
        plt.plot(gens, avgs, linestyle='--', label='Average Fitness')
        plt.axhline(0.5, color='red', linestyle=':', linewidth=1, label='Random-chance baseline')
        plt.xlabel('Generation')
        plt.ylabel('Fitness')
        plt.title('AutoLock GA Fitness')
        plt.legend()
        plt.tight_layout()
        plt.savefig(f"{base_name}_verilog_fitness_history.png", dpi=120)
        plt.close()
        print(f"Saved: {base_name}_verilog_fitness_history.png")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='AutoLock Unified — Logic Locking via GA')
    parser.add_argument('verilog_file', nargs='?', help='Input Verilog file')
    parser.add_argument('--pop-size',    type=int,   default=POPULATION_SIZE,  help='GA population size')
    parser.add_argument('--generations', type=int,   default=NUM_GENERATIONS,  help='Number of GA generations')
    parser.add_argument('--key-length',  type=int,   default=KEY_LENGTH,       help='Key length in bits')
    parser.add_argument('--mutation',    type=float, default=MUTATION_RATE,    help='Mutation rate')
    parser.add_argument('--crossover',   type=float, default=CROSSOVER_RATE,   help='Crossover rate')
    parser.add_argument('--output-base', type=str,   default='best',           help='Output file base name')
    args = parser.parse_args()

    if args.verilog_file:
        try:
            with open(args.verilog_file) as f:
                source = f.read()
            print(f"Loaded: {args.verilog_file}")
            base_name = args.output_base or args.verilog_file.rsplit('.', 1)[0]
        except FileNotFoundError:
            print(f"File not found: {args.verilog_file} — using built-in sample.")
            source = SAMPLE_VERILOG
            base_name = args.output_base
    else:
        print("No file specified — using built-in sample.")
        source = SAMPLE_VERILOG
        base_name = args.output_base

    netlist = parse_verilog(source)
    print(f"Gates: {len(netlist['gates'])} | Inputs: {len(netlist['inputs'])} | Outputs: {len(netlist['outputs'])}")

    graph, nodes = build_graph(netlist)
    if not nodes:
        nodes = netlist['inputs'] + netlist['outputs'] + netlist['wires']
    if len(nodes) < 2:
        nodes = [f"n{i}" for i in range(20)]

    best_individual, best_fitness, history = run_genetic_algorithm(
        netlist, graph, nodes,
        pop_size=args.pop_size,
        num_gen=args.generations,
        key_len=args.key_length,
        mutation_rate=args.mutation,
        crossover_rate=args.crossover,
    )

    verilog_out, key = print_results(netlist, best_individual, best_fitness)
    save_outputs(verilog_out, key, history, base_name=base_name)

    print(f"\nDone. Final best fitness: {best_fitness:.4f}\n")


if __name__ == "__main__":
    main()
