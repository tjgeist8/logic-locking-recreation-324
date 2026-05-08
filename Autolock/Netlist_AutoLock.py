"""
AutoLock — Logic Locking via Genetic Algorithm

Usage:
    python3 Netlist_AutoLock_new.py [verilog_file]

If no file is provided, a built-in sample netlist is used.
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


#------------------------------------------------
# GLOBAL DEFAULTS
#------------------------------------------------

POPULATION_SIZE  = 10
NUM_GENERATIONS  = 50
MUTATION_RATE    = 0.15
CROSSOVER_RATE   = 0.7
KEY_LENGTH       = 128

_ATTACK_TRIALS_GA    = 5
_ATTACK_TRIALS_FINAL = 30

OUTPUT_PORTS = {
    'ZN', 'Z', 'Y', 'Q', 'QN',
    'out', 'y', 'q', 'z', 'o',
    'sum', 'cout',
}

CLOCK_PORTS = {
    'CK', 'CLK', 'clock', 'clk',
    'SE', 'SI', 'CDN', 'SDN'
}

RESERVED_NETS = {
    'clock', 'clk',
    'reset', 'rst',
    'vdd', 'gnd'
}

CONSTANT_RE = re.compile(
    r"\d+'[bhdBHD][0-9a-fA-FxXzZ_]+"
)

SAMPLE_VERILOG = """
module simple_adder (
    input  wire a, b, cin,
    output wire sum, cout
);

    wire w1, w2, w3, w4, w5, w6;

    xor g1 (.a(a),   .b(b),   .out(w1));
    xor g2 (.a(w1),  .b(cin), .out(sum));
    and g3 (.a(a),   .b(b),   .out(w2));
    and g4 (.a(w1),  .b(cin), .out(w3));
    or  g5 (.a(w2),  .b(w3),  .out(cout));
    not g6 (.a(sum), .out(w4));
    and g7 (.a(w4),  .b(cin), .out(w5));
    or  g8 (.a(cout),.b(w5),  .out(w6));
    buf g9 (.a(w6),  .out(w4));

endmodule
"""


#----------------------------------------------
# HELPERS
#----------------------------------------------

def is_constant(signal: str) -> bool:
    return bool(CONSTANT_RE.fullmatch(signal.strip()))


def strip_comments(text: str) -> str:
    """Remove // line comments and /* */ block comments."""
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    return text


#--------------------------------------------
# 1. VERILOG PARSER
#--------------------------------------------

def parse_verilog(source: str) -> dict:
    """Parse gate-instantiation Verilog netlists."""

    src = strip_comments(source)

    netlist = {
        'module': '',
        'inputs': [],
        'outputs': [],
        'wires': [],
        'gates': [],
    }

    m = re.search(r'\bmodule\s+(\w+)', src)
    if m:
        netlist['module'] = m.group(1)

    # Handle both 'input wire' and 'input reg' port declarations
    port_pattern = re.compile(
        r'\b(input|output)\b\s+'
        r'(?:wire\s+)?'
        r'(?:reg\s+)?'
        r'(?:\[(\d+):(\d+)\]\s+)?'
        r'([\w\s,]+);'
    )

    for direction, hi, lo, nets in port_pattern.findall(src):
        names = [n.strip() for n in nets.split(',') if n.strip()]

        if hi != '' and lo != '':
            hi_int = int(hi)
            lo_int = int(lo)
            for name in names:
                for i in range(lo_int, hi_int + 1):
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
    for match in re.finditer(
        r'\bwire\b\s*\[(\d+):(\d+)\]\s+([\w]+)\s*;', src
    ):
        hi, lo, base = int(match.group(1)), int(match.group(2)), match.group(3)
        for i in range(lo, hi + 1):
            netlist['wires'].append(f"{base}[{i}]")

    gate_pattern = re.compile(
        r'(?<![.\w])([A-Za-z]\w*)\s+(\w+)\s*\(([^;]*?)\)\s*;',
        re.DOTALL
    )

    SKIP_KEYWORDS = {
        'module', 'endmodule', 'input', 'output', 'inout',
        'wire', 'reg', 'assign', 'always', 'begin', 'end',
        'if', 'else', 'case', 'endcase', 'for', 'while',
        'posedge', 'negedge', 'parameter', 'localparam',
        'integer', 'genvar', 'generate', 'endgenerate',
    }

    for gtype, gname, port_body in gate_pattern.findall(src):
        if gtype.lower() in SKIP_KEYWORDS:
            continue
        if gname.lower() in SKIP_KEYWORDS:
            continue

        ports = {}
        for pm in re.finditer(r'\.(\w+)\s*\(\s*([^)]+?)\s*\)', port_body):
            ports[pm.group(1)] = pm.group(2).strip()

        if not ports:
            continue

        netlist['gates'].append({
            'name': gname,
            'type': gtype,
            'ports': ports,
        })

    return netlist


#-----------------------------------------------
# 2. DRIVER TABLE
#-----------------------------------------------

def build_driver_table(netlist: dict):
    drivers = {}
    for gate in netlist['gates']:
        for port, net in gate['ports'].items():
            if port in OUTPUT_PORTS:
                drivers[net] = gate['name']
    return drivers


#-------------------------------------------
# 3. CIRCUIT GRAPH
#-------------------------------------------

def build_graph(netlist: dict):

    all_nets = set(
        netlist['inputs'] + netlist['outputs'] + netlist['wires']
    )

    graph = defaultdict(lambda: {'fanout': [], 'fanin': []})

    for gate in netlist['gates']:
        ports = gate['ports']

        out_ports = [p for p in ports if p in OUTPUT_PORTS]
        in_ports  = [p for p in ports if p not in OUTPUT_PORTS and p not in CLOCK_PORTS]

        if not out_ports and ports:
            port_list = list(ports.keys())
            out_ports = [port_list[-1]]
            in_ports  = port_list[:-1]

        for op in out_ports:
            driver = ports[op]
            all_nets.add(driver)

            for ip in in_ports:
                sink = ports[ip]
                if is_constant(sink):
                    continue
                all_nets.add(sink)
                graph[sink]['fanout'].append(driver)
                graph[driver]['fanin'].append(sink)

    return dict(graph), list(all_nets)


# ---------------------------------------------
# 4. GATE I/O HELPERS
# ---------------------------------------------

def _get_gate_io_keys(gate: dict):
    """Return (output_port_keys, input_port_keys) — key names, not net values."""
    ports = gate['ports']
    out_keys = [p for p in ports if p in OUTPUT_PORTS]
    in_keys  = [p for p in ports if p not in OUTPUT_PORTS and p not in CLOCK_PORTS]
    if not out_keys and ports:
        pl = list(ports.keys())
        out_keys = [pl[-1]]
        in_keys  = pl[:-1]
    return out_keys, in_keys


# ---------------------------------------------
# 5. DESCENDANT CHECK
# ---------------------------------------------

def is_descendant(graph, start_node, target_node):
    """Checks if target_node is downstream from start_node."""
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


# ---------------------------------------------
# 6. INITIAL POPULATION
# ---------------------------------------------

def generate_initial_population(netlist, graph, nodes, key_length, pop_size):

    candidates = []

    for gi, gate in enumerate(netlist['gates']):
        _, in_keys = _get_gate_io_keys(gate)
        for port in in_keys:
            signal = gate['ports'].get(port, '')
            if not signal:
                continue
            if port in CLOCK_PORTS:
                continue
            if signal in RESERVED_NETS:
                continue
            if signal in netlist['inputs']:
                continue
            if is_constant(signal):
                continue
            candidates.append((gi, port, signal))

    if not candidates:
        raise RuntimeError("No valid locking candidates found.")

    # Clamp key_length to available candidates to avoid sampling errors
    actual_key_length = min(key_length, len(candidates))
    if actual_key_length < key_length:
        print(
            f"  Warning: only {len(candidates)} candidate locking points found; "
            f"key length clamped from {key_length} to {actual_key_length}."
        )

    population = []

    for _ in range(pop_size):
        individual = []

        # Sample WITHOUT replacement so each locking point is unique per individual
        chosen_points = random.sample(candidates, actual_key_length)

        for gi, port, signal in chosen_points:
            fake_signal = random.choice(nodes)
            attempts = 0
            while (fake_signal == signal or
                   is_constant(fake_signal) or
                   is_descendant(graph, signal, fake_signal)):
                fake_signal = random.choice(nodes)
                attempts += 1
                if attempts > 100:  # Failsafe for sparse graphs
                    break

            key_bit = random.randint(0, 1)
            individual.append((gi, port, signal, fake_signal, key_bit))

        population.append(individual)

    return population


# ---------------------------------------------
# 7. APPLY LOCKING
# ---------------------------------------------

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

        # Wire the true signal to the port matching key_bit
        if key_bit == 1:
            in1_val = signal
            in0_val = fake_signal
        else:
            in1_val = fake_signal
            in0_val = signal

        locked['locking_points'].append({
            'mux': f"KEY_MUX_{idx}",
            'in0': in0_val,
            'in1': in1_val,
            'sel': f"key[{idx}]",
            'out': mux_out,
        })

        locked['key'].append(key_bit)

    locked['wires'].extend(added_wires)
    return locked


# ---------------------------------------------
# 8. ATTACK MODEL
# ---------------------------------------------

def simulate_attack_once(individual, graph, nodes):
    """
    Models a structural attacker who, for each locking MUX, tries to
    identify which of the two inputs (signal vs fake_signal) is the
    'real' wire by comparing their structural properties.

    Attacker heuristic:
      - Compute a plausibility score for each candidate:
            score = degree(wire) / (1 + dist_to_other * 0.1)
        A high-degree wire close to its counterpart looks more like a
        real driver (high connectivity, not an outlier).
      - Whichever candidate scores higher is the attacker's guess for
        the real wire (i.e. the key bit that routes it through).
      - Gaussian noise is added to model imperfect structural analysis.

    Returns the fraction of key bits guessed correctly.
    """

    if not nodes:
        return 0.5

    # Build undirected adjacency for BFS
    adj = defaultdict(set)
    for node, info in graph.items():
        for nb in info.get('fanout', []):
            adj[node].add(nb)
            adj[nb].add(node)
        for nb in info.get('fanin', []):
            adj[node].add(nb)
            adj[nb].add(node)

    def bfs_distance(src, dst):
        """Shortest-path distance between two nets (undirected). 999 = unreachable."""
        if src == dst:
            return 0
        visited = {src}
        queue   = [(src, 0)]
        while queue:
            curr, dist = queue.pop(0)
            for nb in adj.get(curr, set()):
                if nb == dst:
                    return dist + 1
                if nb not in visited:
                    visited.add(nb)
                    queue.append((nb, dist + 1))
        return 999

    def degree(node):
        """Total fanin + fanout of a net."""
        return (
            len(graph.get(node, {}).get('fanout', []))
            + len(graph.get(node, {}).get('fanin',  []))
        )

    correct_guesses = 0

    for (gi, port, signal, fake_signal, key_bit) in individual:

        dist = bfs_distance(signal, fake_signal)

        score_signal = degree(signal)      / (1.0 + dist * 0.1)
        score_fake   = degree(fake_signal) / (1.0 + dist * 0.1)

        # Small noise models imperfect attacker reasoning
        noise = random.gauss(0, 0.05)

        # Attacker picks the higher-scoring wire as the "real" one.
        # key_bit=1 means signal is on in1 (activated when key=1).
        attacker_guess = 1 if (score_signal + noise) >= score_fake else 0

        if attacker_guess == key_bit:
            correct_guesses += 1

    return correct_guesses / len(individual) if individual else 0.5


def simulate_attack(individual, graph, nodes, n_trials=_ATTACK_TRIALS_GA):
    """Average attacker accuracy over multiple independent trials."""
    total = sum(
        simulate_attack_once(individual, graph, nodes)
        for _ in range(n_trials)
    )
    return total / n_trials


def compute_fitness(individual, graph, nodes, n_trials=_ATTACK_TRIALS_GA):
    """
    Fitness = 1 - attacker_accuracy.
    A fitness of 1.0 means the attacker can never guess the key.
    A fitness of 0.5 means the attacker is at random chance (ideal security).
    Values > 0.5 mean we are genuinely harder than random to attack.
    """
    return 1.0 - simulate_attack(individual, graph, nodes, n_trials)


# ---------------------------------------------
# 9. SELECTION
# ---------------------------------------------

def select_parents(population, fitnesses, n_parents):
    TOURNAMENT_SIZE = 3
    parents  = []
    indexed  = list(zip(fitnesses, population))

    for _ in range(n_parents):
        contestants = random.sample(indexed, min(TOURNAMENT_SIZE, len(indexed)))
        winner      = max(contestants, key=lambda x: x[0])
        parents.append(winner[1])

    return parents


# ------------------------------------------
# 10. CROSSOVER
# ------------------------------------------

def crossover(parent_a, parent_b):
    if len(parent_a) <= 1:
        return copy.deepcopy(parent_a), copy.deepcopy(parent_b)

    cut     = random.randint(1, len(parent_a) - 1)
    child_a = parent_a[:cut] + parent_b[cut:]
    child_b = parent_b[:cut] + parent_a[cut:]
    return child_a, child_b


# ---------------------------------------
# 11. MUTATION
# ---------------------------------------

def mutate(individual, netlist, graph, nodes, mutation_rate):
    mutated = copy.deepcopy(individual)

    for i, (gi, port, signal, fake_signal, key_bit) in enumerate(mutated):
        if random.random() < mutation_rate:
            choice = random.randint(0, 1)

            if choice == 0:
                # Swap the fake signal for a different random net
                attempts = 0
                new_fake = random.choice(nodes)
                while (new_fake == signal or
                       is_constant(new_fake) or
                       is_descendant(graph, signal, new_fake)):
                    new_fake = random.choice(nodes)
                    attempts += 1
                    if attempts > 200:  # Failsafe for sparse graphs
                        break
                fake_signal = new_fake
            else:
                # Flip the key bit
                key_bit ^= 1

            mutated[i] = (gi, port, signal, fake_signal, key_bit)

    return mutated


# ---------------------------------------------
# 12. GENETIC ALGORITHM
# ---------------------------------------------

def run_genetic_algorithm(netlist, graph, nodes, pop_size, num_gen, key_len,
                           mutation_rate, crossover_rate):

    print(f"\n{'='*60}")
    print(
        f"  AutoLock GA  |  "
        f"Pop={pop_size}  "
        f"Gen={num_gen}  "
        f"Key={key_len}"
    )
    print(f"{'='*60}\n")

    population = generate_initial_population(
        netlist, graph, nodes, key_len, pop_size
    )

    history           = []
    best_individual   = None
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
            print(
                f"Gen {gen+1:>3}/{num_gen} | "
                f"Best: {gen_best:.4f} | "
                f"Avg: {gen_avg:.4f}"
            )

        parents = select_parents(population, fitnesses, pop_size)

        # Elitism: carry forward the best individual unchanged
        new_population = [copy.deepcopy(population[best_idx])]

        while len(new_population) < pop_size:
            pa, pb = random.sample(parents, 2)

            if random.random() < crossover_rate:
                child_a, child_b = crossover(pa, pb)
            else:
                child_a = copy.deepcopy(pa)
                child_b = copy.deepcopy(pb)

            child_a = mutate(child_a, netlist, graph, nodes, mutation_rate)
            child_b = mutate(child_b, netlist, graph, nodes, mutation_rate)

            new_population.append(child_a)
            if len(new_population) < pop_size:
                new_population.append(child_b)

        population = new_population

    print(f"\nRe-evaluating champion over {_ATTACK_TRIALS_FINAL} trials...")

    best_fitness_final = compute_fitness(
        best_individual, graph, nodes, n_trials=_ATTACK_TRIALS_FINAL
    )

    return best_individual, best_fitness_final, history


#------------------------------------------
# 13. VERILOG OUTPUT
#------------------------------------------

def format_locked_verilog(netlist, locked):

    lines = []
    mod   = netlist.get('module', 'locked_circuit')
    key   = locked.get('key', [])
    lps   = locked.get('locking_points', [])

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

    wire_list = list(dict.fromkeys([
        w for w in locked['wires'] if w not in netlist['outputs']
    ]))

    if wire_list:
        # Chunk wire declarations into groups of 8 for readability
        for i in range(0, len(wire_list), 8):
            chunk = wire_list[i:i+8]
            lines.append("    wire " + ", ".join(chunk) + ";")
        lines.append("")

    lines.append("    // Original gates")
    for g in locked['gates']:
        port_str = ", ".join(f".{p}({n})" for p, n in g['ports'].items())
        lines.append(f"    {g['type']} {g['name']} ({port_str});")

    lines.append("")
    lines.append("    // Locking MUXes")
    for lp in lps:
        lines.append(
            f"    mux2 {lp['mux']} ("
            f".in0({lp['in0']}), "
            f".in1({lp['in1']}), "
            f".sel({lp['sel']}), "
            f".out({lp['out']})"
            f");"
        )

    lines.append("")
    lines.append("endmodule")
    return "\n".join(lines)


# -------------------------------------------
# 14. RESULTS
# -------------------------------------------

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

    verilog_out = format_locked_verilog(netlist, locked)
    return verilog_out, key


def save_outputs(verilog_out, key, history, base_name="best"):

    v_file = f"{base_name}_locked_netlist.v"
    k_file = f"{base_name}_netlist_key.txt"

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
        plt.savefig(f"{base_name}_netlist_fitness_history.png", dpi=120)
        plt.close()
        print(f"Saved: {base_name}_netlist_fitness_history.png")


# ---------------------------------------------
# MAIN
# ---------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description='AutoLock — Logic Locking via GA (Netlist Mode)'
    )
    parser.add_argument('verilog_file',  nargs='?',    help='Input Verilog netlist file')
    parser.add_argument('--pop-size',    type=int,     default=POPULATION_SIZE,  help='GA population size')
    parser.add_argument('--generations', type=int,     default=NUM_GENERATIONS,  help='Number of GA generations')
    parser.add_argument('--key-length',  type=int,     default=KEY_LENGTH,       help='Key length in bits')
    parser.add_argument('--mutation',    type=float,   default=MUTATION_RATE,    help='Mutation rate')
    parser.add_argument('--crossover',   type=float,   default=CROSSOVER_RATE,   help='Crossover rate')
    parser.add_argument('--output-base', type=str,     default='best',           help='Output file base name')
    args = parser.parse_args()

    if args.verilog_file:
        try:
            with open(args.verilog_file) as f:
                source = f.read()
            print(f"Loaded Verilog from: {args.verilog_file}")
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
