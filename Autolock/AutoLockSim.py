"""
Usage:
    python autolock_sim.py [verilog_file]
    If no file is provided, a built-in sample netlist is used.
"""

import random
import copy
import sys
import re
from collections import defaultdict

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# ─────────────────────────────────────────────
# GLOBAL CONFIGURATION
# ─────────────────────────────────────────────
POPULATION_SIZE  = 15     # Number of individuals in each generation
NUM_GENERATIONS  = 10     # Total generations to evolve
MUTATION_RATE    = 0.15   # Probability of mutating each locking point
CROSSOVER_RATE   = 0.7    # Probability of applying crossover vs. cloning
KEY_LENGTH       = 4      # Number of MUX locking points to insert

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


# ─────────────────────────────────────────────
# 1. VERILOG PARSER
# ─────────────────────────────────────────────

def parse_verilog(source: str) -> dict:
    """
    Simplified Verilog gate-level parser.

    Returns a dict:
      {
        'module'  : str,          # module name
        'inputs'  : [str],        # primary input ports
        'outputs' : [str],        # primary output ports
        'wires'   : [str],        # internal wire names
        'gates'   : [             # list of gate instances
            {'name': str, 'type': str, 'ports': {port: net, ...}},
            ...
        ]
      }
    """
    netlist = {'module': '', 'inputs': [], 'outputs': [], 'wires': [], 'gates': []}

    # Module name
    m = re.search(r'\bmodule\s+(\w+)', source)
    if m:
        netlist['module'] = m.group(1)

    # Ports declarations
    for kw in ('input', 'output'):
        for net in re.findall(rf'\b{kw}\b\s+(?:wire\s+)?([\w\s,]+);', source):
            names = [n.strip() for n in net.split(',') if n.strip()]
            netlist[kw + 's'].extend(names)

    # Wire declarations
    for net in re.findall(r'\bwire\b\s+([\w\s,]+);', source):
        names = [n.strip() for n in net.split(',') if n.strip()]
        netlist['wires'].extend(names)

    # ── Gate instance parser ───────────────────────────────────────────────
    # Handles BOTH:
    #   • Basic Verilog primitives:  and g1 (.a(x), .b(y), .out(z));
    #   • Yosys standard-cell names: NAND2_X1 _52_ (.A1(x), .A2(y), .ZN(z));
    #     Recognised families: INV, BUF, AND, OR, NAND, NOR, XOR, XNOR,
    #                          AOI, OAI, MUX, DFF, DFFR, DFFS, DFFRS, …
    #
    # Pattern: <CellType> <InstanceName> ( <port-list> );
    # CellType must start with a letter and contain only word chars (no spaces).
    # We skip the reserved keyword "module" and port/wire declarations.
    gate_pattern = re.compile(
        r'(?<![.\w])'                    # not preceded by dot or word char
        r'([A-Za-z]\w*)'                 # group 1: cell/gate type
        r'\s+(\w+)'                      # group 2: instance name
        r'\s*\(([^;]*?)\)\s*;',          # group 3: port list (up to semicolon)
        re.DOTALL
    )
    # Keywords that are NOT gate types
    SKIP_KEYWORDS = {
        'module', 'endmodule', 'input', 'output', 'inout',
        'wire', 'reg', 'assign', 'always', 'begin', 'end',
        'if', 'else', 'case', 'endcase', 'for', 'while',
        'posedge', 'negedge', 'parameter', 'localparam',
        'integer', 'genvar', 'generate', 'endgenerate',
    }

    # Map Yosys output-port names to a canonical 'out' label for graph building
    # Input ports for common cell families
    YOSYS_OUTPUT_PORTS = {
        # Standard logic
        'ZN', 'Z', 'Y', 'Q', 'QN',
        # Basic primitives
        'out', 'y', 'q', 'z', 'o', 'sum', 'cout',
    }

    for gtype, gname, port_body in gate_pattern.findall(source):
        if gtype.lower() in SKIP_KEYWORDS:
            continue
        # Skip pure wire/reg declarations caught by the broad pattern
        if gname.lower() in SKIP_KEYWORDS:
            continue

        ports = {}
        for pm in re.finditer(r'\.(\w+)\s*\(\s*([\w\[\]]+)\s*\)', port_body):
            ports[pm.group(1)] = pm.group(2)

        if not ports:
            continue  # empty port list → not a real gate instance

        netlist['gates'].append({
            'name' : gname,
            'type' : gtype,       # keep original name (INV_X1, NAND2_X1, …)
            'ports': ports,
        })

    # ── Also parse vector wire declarations  wire [7:0] stato; ─────────────
    for match in re.finditer(r'\bwire\b\s*\[(\d+):(\d+)\]\s+([\w]+)\s*;', source):
        hi, lo, base = int(match.group(1)), int(match.group(2)), match.group(3)
        for i in range(lo, hi + 1):
            netlist['wires'].append(f"{base}[{i}]")

    return netlist


# ─────────────────────────────────────────────
# 2. CIRCUIT GRAPH
# ─────────────────────────────────────────────

def build_graph(netlist: dict):
    """
    Build a directed graph where nodes are nets (wires/ports)
    and edges represent gate connections (driver → sink).

    Handles both basic Verilog primitives and Yosys standard-cell output
    port names (ZN, Z, Y, Q, QN).

    Returns:
        graph  : dict  {node: {'fanout': [node], 'fanin': [node]}}
        nodes  : list of all net names
    """
    all_nets = set(netlist['inputs'] + netlist['outputs'] + netlist['wires'])

    # Ports that are OUTPUTS of a gate (drive a net)
    # Yosys uses ZN / Z for combinational, Q / QN for flip-flops
    OUTPUT_PORTS = {
        'ZN', 'Z', 'Y', 'Q',          # Yosys standard-cell outputs
        'out', 'y', 'q', 'z', 'o',    # generic primitives
        'sum', 'cout',                  # arithmetic primitives
    }
    # QN is a complementary (inverted) output — it drives a net too
    ALSO_OUTPUT = {'QN'}
    # Clock/scan/enable ports — not signal-path connections
    CLOCK_PORTS = {'CK', 'CLK', 'SE', 'SI', 'CDN', 'SDN'}

    graph = defaultdict(lambda: {'fanout': [], 'fanin': []})

    for gate in netlist['gates']:
        ports = gate['ports']
        if not ports:
            continue

        out_ports = [p for p in ports if p in OUTPUT_PORTS or p in ALSO_OUTPUT]
        in_ports  = [p for p in ports
                     if p not in OUTPUT_PORTS
                     and p not in ALSO_OUTPUT
                     and p not in CLOCK_PORTS]

        # Fallback: no recognised output port → treat last port as output
        if not out_ports and ports:
            port_list = list(ports.keys())
            out_ports = [port_list[-1]]
            in_ports  = port_list[:-1]

        for op in out_ports:
            driver = ports[op]
            all_nets.add(driver)
            for ip in in_ports:
                sink = ports[ip]
                all_nets.add(sink)
                graph[driver]['fanout'].append(sink)
                graph[sink]['fanin'].append(driver)

    return dict(graph), list(all_nets)


# ─────────────────────────────────────────────
# 3. INITIAL POPULATION
# ─────────────────────────────────────────────

def generate_initial_population(nodes: list, key_length: int, pop_size: int) -> list:
    """
    Create a list of POPULATION_SIZE random locking configurations.

    Each individual (genotype) is a list of KEY_LENGTH tuples:
        (node_a, node_b, node_c, node_d, key_bit)

    Where a MUX locking point is conceptually:
        If key_bit == 1: forward signal from node_a to node_b  (correct)
        If key_bit == 0: forward signal from node_c to node_d  (obfuscated)
    """
    population = []
    for _ in range(pop_size):
        individual = []
        for _ in range(key_length):
            a, b, c, d = random.choices(nodes, k=4)
            key_bit = random.randint(0, 1)
            individual.append((a, b, c, d, key_bit))
        population.append(individual)
    return population


# ─────────────────────────────────────────────
# 4. APPLY LOCKING (conceptual representation)
# ─────────────────────────────────────────────

def apply_locking(netlist: dict, individual: list) -> dict:
    """
    Return a new netlist dict annotated with the locking points
    from the given individual (genotype).

    Each locking point adds a MUX gate conceptually controlled by a key bit.
    """
    locked = copy.deepcopy(netlist)
    locked['locking_points'] = []
    locked['key'] = []

    for idx, (a, b, c, d, key_bit) in enumerate(individual):
        mux_name = f"KEY_MUX_{idx}"
        locked['locking_points'].append({
            'mux'     : mux_name,
            'in0'     : c,          # wrong path (when key=0)
            'in1'     : a,          # correct path (when key=1)
            'sel'     : f"key[{idx}]",
            'out'     : b,
        })
        locked['key'].append(key_bit)

    return locked


# ─────────────────────────────────────────────
# 5. SIMULATED ATTACK
# ─────────────────────────────────────────────

def simulate_attack_once(individual: list, graph: dict, nodes: list) -> float:
    """
    Simplified structural attack model (inspired by MuxLink heuristics).

    The attacker tries to guess the correct key bit for each locking point
    using structural properties of the circuit graph.

    Heuristics used:
      1. Fan-in/fan-out similarity: if node_a and node_b have similar
         connectivity degrees, they are likely correctly paired.
      2. Shortest-path bias: if node_a→node_b is shorter than node_c→node_d,
         the attacker prefers (a→b) as the true connection.
      3. A small random noise term prevents perfect determinism.

    Returns:
        attack_accuracy  (float in [0, 1])
        1.0 = attacker guesses all key bits correctly
        0.0 = attacker guesses nothing
    """
    if not nodes:
        return 0.5

    # Build simple adjacency for BFS distance
    adj = defaultdict(set)
    for node, info in graph.items():
        for nb in info.get('fanout', []):
            adj[node].add(nb)
        for nb in info.get('fanin', []):
            adj[nb].add(node)

    def bfs_distance(src, dst):
        """Undirected BFS distance; returns large number if unreachable."""
        if src == dst:
            return 0
        visited = {src}
        queue = [(src, 0)]
        while queue:
            curr, dist = queue.pop(0)
            for nb in adj.get(curr, []):
                if nb == dst:
                    return dist + 1
                if nb not in visited:
                    visited.add(nb)
                    queue.append((nb, dist + 1))
        return 999  # unreachable

    def degree(node):
        fanout = len(graph.get(node, {}).get('fanout', []))
        fanin  = len(graph.get(node, {}).get('fanin', []))
        return fanout + fanin

    correct_guesses = 0

    for (a, b, c, d, key_bit) in individual:
        # Heuristic 1: structural similarity score for (a→b) vs (c→d)
        sim_ab = 1.0 / (1 + abs(degree(a) - degree(b)))
        sim_cd = 1.0 / (1 + abs(degree(c) - degree(d)))

        # Heuristic 2: shorter path is more likely to be the real connection
        dist_ab = bfs_distance(a, b)
        dist_cd = bfs_distance(c, d)

        score_ab = sim_ab / (1 + dist_ab * 0.1)
        score_cd = sim_cd / (1 + dist_cd * 0.1)

        # Attacker guesses key_bit=1 if (a→b) looks more structural
        # attacker guesses key_bit=0 otherwise
        noise = random.uniform(-0.05, 0.05)
        attacker_guess = 1 if (score_ab + noise) >= score_cd else 0

        if attacker_guess == key_bit:
            correct_guesses += 1

    attack_accuracy = correct_guesses / len(individual) if individual else 0.5
    return attack_accuracy


# ─────────────────────────────────────────────
# 6. FITNESS
# ─────────────────────────────────────────────

# How many attack trials to average when evaluating an individual.
# During the GA loop a small N keeps things fast; final scoring uses a larger N.
_ATTACK_TRIALS_GA    = 5    # trials per individual during evolution
_ATTACK_TRIALS_FINAL = 30   # trials for the definitive end-of-run score


def simulate_attack(individual: list, graph: dict, nodes: list,
                    n_trials: int = _ATTACK_TRIALS_GA) -> float:
    """
    Average attack_accuracy over n_trials independent runs of the noisy
    structural attack.  Averaging smooths out the ±noise so that a genuinely
    hard-to-attack individual consistently scores near 0 and an easy one
    consistently scores near 1.

    Returns: mean attack_accuracy in [0, 1]
    """
    total = sum(simulate_attack_once(individual, graph, nodes)
                for _ in range(n_trials))
    return total / n_trials


def compute_fitness(individual: list, graph: dict, nodes: list,
                    n_trials: int = _ATTACK_TRIALS_GA) -> float:
    """
    fitness = 1 - attack_accuracy  (averaged over n_trials).

    Higher fitness → harder to attack → more secure locking.
    """
    return 1.0 - simulate_attack(individual, graph, nodes, n_trials)


# ─────────────────────────────────────────────
# 7. SELECTION
# ─────────────────────────────────────────────

def select_parents(population: list, fitnesses: list, n_parents: int) -> list:
    """
    Tournament selection: randomly pick k candidates, keep the best.
    Repeat until n_parents are selected.
    """
    TOURNAMENT_SIZE = 3
    parents = []
    indexed = list(zip(fitnesses, population))
    for _ in range(n_parents):
        contestants = random.sample(indexed, min(TOURNAMENT_SIZE, len(indexed)))
        winner = max(contestants, key=lambda x: x[0])
        parents.append(winner[1])
    return parents


# ─────────────────────────────────────────────
# 8. CROSSOVER
# ─────────────────────────────────────────────

def crossover(parent_a: list, parent_b: list) -> tuple:
    """
    Single-point crossover on the list of locking points.

    Returns two children (offspring).
    """
    if len(parent_a) <= 1:
        return copy.deepcopy(parent_a), copy.deepcopy(parent_b)

    cut = random.randint(1, len(parent_a) - 1)
    child_a = parent_a[:cut] + parent_b[cut:]
    child_b = parent_b[:cut] + parent_a[cut:]
    return child_a, child_b


# ─────────────────────────────────────────────
# 9. MUTATION
# ─────────────────────────────────────────────

def mutate(individual: list, nodes: list, mutation_rate: float) -> list:
    """
    For each locking point, with probability mutation_rate:
      - Randomly replace one of the four nodes, OR
      - Flip the key bit.
    """
    mutated = copy.deepcopy(individual)
    for i, (a, b, c, d, key_bit) in enumerate(mutated):
        if random.random() < mutation_rate:
            choice = random.randint(0, 4)
            if choice == 0:
                a = random.choice(nodes)
            elif choice == 1:
                b = random.choice(nodes)
            elif choice == 2:
                c = random.choice(nodes)
            elif choice == 3:
                d = random.choice(nodes)
            else:
                key_bit = 1 - key_bit   # flip key bit
            mutated[i] = (a, b, c, d, key_bit)
    return mutated


# ─────────────────────────────────────────────
# 10. GENETIC ALGORITHM MAIN LOOP
# ─────────────────────────────────────────────

def run_genetic_algorithm(netlist: dict, graph: dict, nodes: list) -> tuple:
    """
    Main GA loop.

    Each generation's fitness scores are averaged over _ATTACK_TRIALS_GA
    independent attack trials, which removes single-roll luck from rankings.

    After the loop, the overall best individual is re-evaluated with
    _ATTACK_TRIALS_FINAL trials to produce a stable, trustworthy final score.

    Returns:
        best_individual      : list of locking point tuples
        best_fitness_final   : float  (averaged over _ATTACK_TRIALS_FINAL trials)
        history              : list of (gen_best_avg, gen_avg_avg) per generation
    """
    print(f"\n{'='*55}")
    print(f"  AutoLock GA  |  Pop={POPULATION_SIZE}  Gen={NUM_GENERATIONS}  Key={KEY_LENGTH}")
    print(f"  Attack trials per eval (GA): {_ATTACK_TRIALS_GA}  |  final: {_ATTACK_TRIALS_FINAL}")
    print(f"{'='*55}\n")

    population   = generate_initial_population(nodes, KEY_LENGTH, POPULATION_SIZE)
    history      = []
    best_individual   = None
    best_fitness_seen = -1.0   # best averaged fitness seen across all generations

    for gen in range(NUM_GENERATIONS):
        # ── Evaluate every individual (averaged over _ATTACK_TRIALS_GA trials)
        fitnesses = [compute_fitness(ind, graph, nodes) for ind in population]

        gen_best = max(fitnesses)
        gen_avg  = sum(fitnesses) / len(fitnesses)
        history.append((gen_best, gen_avg))

        # ── Update the all-time champion
        best_idx = fitnesses.index(gen_best)
        if gen_best > best_fitness_seen:
            best_fitness_seen = gen_best
            best_individual   = copy.deepcopy(population[best_idx])

        if (gen + 1) % 10 == 0 or gen == 0:
            print(f"  Gen {gen+1:>3}/{NUM_GENERATIONS}  |  "
                  f"Best Fitness: {gen_best:.4f}  |  Avg: {gen_avg:.4f}")

        # ── Selection
        parents = select_parents(population, fitnesses, POPULATION_SIZE)

        # ── Build next generation
        new_population = []

        # Elitism: the current generation's best goes through unchanged
        # (Note: we insert the *generation* winner, not the all-time champion,
        #  so elitism actually protects what selection just found.)
        new_population.append(copy.deepcopy(population[best_idx]))

        while len(new_population) < POPULATION_SIZE:
            pa, pb = random.sample(parents, 2)
            if random.random() < CROSSOVER_RATE:
                child_a, child_b = crossover(pa, pb)
            else:
                child_a, child_b = copy.deepcopy(pa), copy.deepcopy(pb)

            child_a = mutate(child_a, nodes, MUTATION_RATE)
            child_b = mutate(child_b, nodes, MUTATION_RATE)

            new_population.append(child_a)
            if len(new_population) < POPULATION_SIZE:
                new_population.append(child_b)

        population = new_population

    # ── Final stable evaluation of the champion
    # Re-evaluate with many trials so the reported score isn't a lucky roll.
    print(f"\n  Re-evaluating champion over {_ATTACK_TRIALS_FINAL} trials...")
    best_fitness_final = compute_fitness(best_individual, graph, nodes,
                                         n_trials=_ATTACK_TRIALS_FINAL)
    print(f"  Champion fitness (final): {best_fitness_final:.4f}  "
          f"(best seen during run: {best_fitness_seen:.4f})")

    return best_individual, best_fitness_final, history


# ─────────────────────────────────────────────
# 11. OUTPUT
# ─────────────────────────────────────────────

def format_locked_verilog(netlist: dict, locked: dict) -> str:
    """
    Produce a Verilog-like text for the locked circuit.
    """
    lines = []
    mod   = netlist.get('module', 'locked_circuit')
    key   = locked.get('key', [])
    lps   = locked.get('locking_points', [])

    key_ports = ', '.join(f'key[{i}]' for i in range(len(key)))
    inp_str   = ', '.join(netlist.get('inputs', []))
    out_str   = ', '.join(netlist.get('outputs', []))

    lines.append(f"// AutoLock-generated locked netlist")
    lines.append(f"// Correct key: {key}")
    lines.append(f"module {mod}_locked (")
    lines.append(f"    input  wire [{len(key)-1}:0] key,")
    lines.append(f"    input  wire {inp_str},")
    lines.append(f"    output wire {out_str}")
    lines.append(");")
    lines.append("")

    if netlist.get('wires'):
        lines.append("    wire " + ", ".join(netlist['wires']) + ";")
        lines.append("")

    lines.append("    // ── Original gates ──────────────────────────")
    for g in netlist.get('gates', []):
        port_str = ", ".join(f".{p}({n})" for p, n in g['ports'].items())
        lines.append(f"    {g['type']} {g['name']} ({port_str});")

    lines.append("")
    lines.append("    // ── MUX Locking Points ──────────────────────")
    for lp in lps:
        lines.append(
            f"    mux2 {lp['mux']} (.in0({lp['in0']}), .in1({lp['in1']}), "
            f".sel({lp['sel']}), .out({lp['out']}));"
        )

    lines.append("")
    lines.append("endmodule")
    return "\n".join(lines)


def print_results(netlist, best_individual, best_fitness, history):
    """Print summary results to stdout.

    best_fitness is the score recorded during the GA run — we report it
    directly rather than re-evaluating (the attack has random noise so a
    fresh call could give a different number).
    """
    locked = apply_locking(netlist, best_individual)
    key    = locked['key']
    attack_acc = 1.0 - best_fitness   # uses stored score, not a new roll

    print(f"\n{'='*55}")
    print("  RESULTS")
    print(f"{'='*55}")
    print(f"  Best Fitness      : {best_fitness:.4f}")
    print(f"  Attack Accuracy   : {attack_acc:.4f}  (lower = more secure)")
    print(f"  Key Length        : {len(key)} bits")
    print(f"  Correct Key       : {''.join(str(b) for b in key)}")
    print(f"  Generations run   : {len(history)}")
    print()
    print("  Locking Points:")
    for i, lp in enumerate(locked['locking_points']):
        print(f"    [{i}] MUX sel=key[{i}]={key[i]}  "
              f"in1(correct)={lp['in1']}→{lp['out']}  "
              f"in0(decoy)={lp['in0']}")
    print()

    verilog_out = format_locked_verilog(netlist, locked)
    #print("── Locked Verilog ──────────────────────────────────")
    #print(verilog_out)

    return verilog_out, key


def save_outputs(verilog_out: str, key: list, history: list):
    """Save locked Verilog and optionally plot fitness history."""
    with open("best_locked_circuit.v", "w") as f:
        f.write(verilog_out)
    print("\n  Saved: best_locked_circuit.v")

    with open("best_key.txt", "w") as f:
        f.write("Correct key (binary): " + ''.join(str(b) for b in key) + "\n")
        f.write("Key bits: " + str(key) + "\n")
    print("  Saved: best_key.txt")

    if HAS_MATPLOTLIB and history:
        gens       = range(1, len(history) + 1)
        bests      = [h[0] for h in history]
        avgs       = [h[1] for h in history]

        plt.figure(figsize=(9, 4))
        plt.plot(gens, bests, label='Best Fitness',    color='steelblue', linewidth=2)
        plt.plot(gens, avgs,  label='Average Fitness', color='coral',     linestyle='--')
        plt.xlabel('Generation')
        plt.ylabel('Fitness  (1 − attack accuracy)')
        plt.title('AutoLock GA — Fitness Over Generations')
        plt.legend()
        plt.tight_layout()
        plt.savefig("fitness_history.png", dpi=120)
        plt.close()
        print("  Saved: fitness_history.png")
    elif not HAS_MATPLOTLIB:
        print("  (matplotlib not available — skipping plot)")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def main():
    # Load Verilog source
    if len(sys.argv) > 1:
        verilog_file = sys.argv[1]
        try:
            with open(verilog_file) as f:
                source = f.read()
            print(f"Loaded Verilog from: {verilog_file}")
        except FileNotFoundError:
            print(f"File not found: {verilog_file}. Using built-in sample.")
            source = SAMPLE_VERILOG
    else:
        print("No file specified — using built-in sample netlist.")
        source = SAMPLE_VERILOG

    # Parse
    netlist = parse_verilog(source)
    #print(f"Module  : {netlist['module']}")
    #print(f"Inputs  : {netlist['inputs']}")
    #print(f"Outputs : {netlist['outputs']}")
    #print(f"Wires   : {netlist['wires']}")
    print(f"Gates   : {len(netlist['gates'])}")

    # Build graph
    graph, nodes = build_graph(netlist)
    #print(f"Graph nodes: {len(nodes)}")

    if not nodes:
        # Fallback: use input/output/wire names directly
        nodes = netlist['inputs'] + netlist['outputs'] + netlist['wires']

    if len(nodes) < 2:
        print("WARNING: Very few nodes found — using synthetic placeholders.")
        nodes = [f"n{i}" for i in range(20)]

    # Run GA
    best_individual, best_fitness, history = run_genetic_algorithm(netlist, graph, nodes)

    # Output
    verilog_out, key = print_results(netlist, best_individual, best_fitness, history)
    save_outputs(verilog_out, key, history)

    print(f"\nDone.  Final best fitness: {best_fitness:.4f}\n")


if __name__ == "__main__":
    main()
