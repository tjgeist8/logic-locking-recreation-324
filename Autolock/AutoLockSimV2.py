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

POPULATION_SIZE  = 10
NUM_GENERATIONS  = 50
MUTATION_RATE    = 0.15
CROSSOVER_RATE   = 0.7
KEY_LENGTH       = 32

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


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def is_constant(signal: str) -> bool:
    return bool(CONSTANT_RE.fullmatch(signal.strip()))


# ─────────────────────────────────────────────
# 1. VERILOG PARSER
# ─────────────────────────────────────────────

def parse_verilog(source: str) -> dict:

    netlist = {
        'module': '',
        'inputs': [],
        'outputs': [],
        'wires': [],
        'gates': [],
    }

    # Module name
    m = re.search(r'\bmodule\s+(\w+)', source)
    if m:
        netlist['module'] = m.group(1)

    # Ports declarations (supports vectors like [3:0])
    port_pattern = re.compile(
        r'\b(input|output)\b\s+'
        r'(?:wire\s+)?'
        r'(?:\[(\d+):(\d+)\]\s+)?'
        r'([\w\s,]+);'
    )

    for direction, hi, lo, nets in port_pattern.findall(source):
        names = [n.strip() for n in nets.split(',') if n.strip()]

        # Vector ports
        if hi != '' and lo != '':
            hi_int = int(hi)
            lo_int = int(lo)

            for name in names:
                for i in range(lo_int, hi_int + 1):
                    netlist[direction + 's'].append(f"{name}[{i}]")

        # Scalar ports
        else:
            netlist[direction + 's'].extend(names)

    # Scalar wires
    for net in re.findall(
        r'\bwire\b\s+([\w\s,]+);',
        source
    ):

        if '[' in net:
            continue

        names = [
            n.strip()
            for n in net.split(',')
            if n.strip()
        ]

        netlist['wires'].extend(names)

    # Vector wires
    for match in re.finditer(
        r'\bwire\b\s*\[(\d+):(\d+)\]\s+([\w]+)\s*;',
        source
    ):

        hi, lo, base = (
            int(match.group(1)),
            int(match.group(2)),
            match.group(3)
        )

        for i in range(lo, hi + 1):
            netlist['wires'].append(f"{base}[{i}]")

    # Gate parser
    gate_pattern = re.compile(
        r'(?<![.\w])'
        r'([A-Za-z]\w*)'
        r'\s+(\w+)'
        r'\s*\(([^;]*?)\)\s*;',
        re.DOTALL
    )

    SKIP_KEYWORDS = {
        'module', 'endmodule',
        'input', 'output', 'inout',
        'wire', 'reg', 'assign',
        'always', 'begin', 'end',
        'if', 'else',
        'case', 'endcase',
        'for', 'while',
        'posedge', 'negedge',
        'parameter', 'localparam',
        'integer', 'genvar',
        'generate', 'endgenerate',
    }

    for gtype, gname, port_body in gate_pattern.findall(source):

        if gtype.lower() in SKIP_KEYWORDS:
            continue

        if gname.lower() in SKIP_KEYWORDS:
            continue

        ports = {}

        # FIXED parser regex
        for pm in re.finditer(
            r'\.(\w+)\s*\(\s*([^)]+?)\s*\)',
            port_body
        ):
            ports[pm.group(1)] = pm.group(2).strip()

        if not ports:
            continue

        netlist['gates'].append({
            'name': gname,
            'type': gtype,
            'ports': ports,
        })

    return netlist


# ─────────────────────────────────────────────
# 2. DRIVER TABLE
# ─────────────────────────────────────────────

def build_driver_table(netlist: dict):

    drivers = {}

    for gate in netlist['gates']:

        for port, net in gate['ports'].items():

            if port in OUTPUT_PORTS:
                drivers[net] = gate['name']

    return drivers


# ─────────────────────────────────────────────
# 3. CIRCUIT GRAPH
# ─────────────────────────────────────────────

def build_graph(netlist: dict):

    all_nets = set(
        netlist['inputs']
        + netlist['outputs']
        + netlist['wires']
    )

    graph = defaultdict(
        lambda: {
            'fanout': [],
            'fanin': [],
        }
    )

    for gate in netlist['gates']:

        ports = gate['ports']

        out_ports = [
            p for p in ports
            if p in OUTPUT_PORTS
        ]

        in_ports = [
            p for p in ports
            if p not in OUTPUT_PORTS
            and p not in CLOCK_PORTS
        ]

        if not out_ports and ports:
            port_list = list(ports.keys())
            out_ports = [port_list[-1]]
            in_ports = port_list[:-1]

        for op in out_ports:

            driver = ports[op]
            all_nets.add(driver)

            for ip in in_ports:

                sink = ports[ip]

                if is_constant(sink):
                    continue

                all_nets.add(sink)

                graph[driver]['fanout'].append(sink)
                graph[sink]['fanin'].append(driver)

    return dict(graph), list(all_nets)


# ─────────────────────────────────────────────
# 4. INITIAL POPULATION
# ─────────────────────────────────────────────

def generate_initial_population(
    netlist,
    nodes,
    key_length,
    pop_size
):

    candidates = []

    for gi, gate in enumerate(netlist['gates']):

        for port, signal in gate['ports'].items():

            if port in OUTPUT_PORTS:
                continue

            if port in CLOCK_PORTS:
                continue

            if signal in RESERVED_NETS:
                continue

            if signal in netlist['inputs']:
                continue

            if is_constant(signal):
                continue

            candidates.append(
                (gi, port, signal)
            )

    if not candidates:
        raise RuntimeError(
            "No valid locking candidates found."
        )

    population = []

    for _ in range(pop_size):

        individual = []

        for _ in range(key_length):

            gi, port, signal = random.choice(candidates)

            fake_signal = random.choice(nodes)

            while (
                fake_signal == signal
                or is_constant(fake_signal)
            ):
                fake_signal = random.choice(nodes)

            key_bit = random.randint(0, 1)

            individual.append(
                (
                    gi,
                    port,
                    signal,
                    fake_signal,
                    key_bit
                )
            )

        population.append(individual)

    return population


# ─────────────────────────────────────────────
# 5. APPLY LOCKING
# ─────────────────────────────────────────────

def apply_locking(netlist: dict, individual: list):

    locked = copy.deepcopy(netlist)

    locked['locking_points'] = []
    locked['key'] = []

    added_wires = []

    for idx, (
        gi,
        port,
        signal,
        fake_signal,
        key_bit
    ) in enumerate(individual):

        mux_out = f"lock_net_{idx}"

        added_wires.append(mux_out)

        gate = locked['gates'][gi]

        gate['ports'][port] = mux_out

        locked['locking_points'].append({
            'mux': f"KEY_MUX_{idx}",
            'in0': fake_signal,
            'in1': signal,
            'sel': f"key[{idx}]",
            'out': mux_out,
        })

        locked['key'].append(key_bit)

    locked['wires'].extend(added_wires)

    return locked


# ─────────────────────────────────────────────
# 6. ATTACK MODEL
# ─────────────────────────────────────────────

def simulate_attack_once(
    individual,
    graph,
    nodes
):

    if not nodes:
        return 0.5

    adj = defaultdict(set)

    for node, info in graph.items():

        for nb in info.get('fanout', []):
            adj[node].add(nb)

        for nb in info.get('fanin', []):
            adj[nb].add(node)

    def bfs_distance(src, dst):

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

        return 999

    def degree(node):

        fanout = len(
            graph.get(node, {}).get('fanout', [])
        )

        fanin = len(
            graph.get(node, {}).get('fanin', [])
        )

        return fanout + fanin

    correct_guesses = 0

    for (
        gi,
        port,
        signal,
        fake_signal,
        key_bit
    ) in individual:

        sim_real = 1.0 / (
            1 + abs(
                degree(signal)
                - degree(signal)
            )
        )

        sim_fake = 1.0 / (
            1 + abs(
                degree(signal)
                - degree(fake_signal)
            )
        )

        dist_real = bfs_distance(signal, signal)
        dist_fake = bfs_distance(signal, fake_signal)

        score_real = sim_real / (1 + dist_real * 0.1)
        score_fake = sim_fake / (1 + dist_fake * 0.1)

        noise = random.uniform(-0.01, 0.01)

        attacker_guess = (
            1 if (score_real + noise) >= score_fake
            else 0
        )

        if attacker_guess == key_bit:
            correct_guesses += 1

    return (
        correct_guesses / len(individual)
        if individual else 0.5
    )


def simulate_attack(
    individual,
    graph,
    nodes,
    n_trials=_ATTACK_TRIALS_GA
):

    total = sum(
        simulate_attack_once(
            individual,
            graph,
            nodes
        )
        for _ in range(n_trials)
    )

    return total / n_trials


def compute_fitness(
    individual,
    graph,
    nodes,
    n_trials=_ATTACK_TRIALS_GA
):

    return 1.0 - simulate_attack(
        individual,
        graph,
        nodes,
        n_trials
    )


# ─────────────────────────────────────────────
# 7. SELECTION
# ─────────────────────────────────────────────

def select_parents(
    population,
    fitnesses,
    n_parents
):

    TOURNAMENT_SIZE = 3

    parents = []

    indexed = list(zip(fitnesses, population))

    for _ in range(n_parents):

        contestants = random.sample(
            indexed,
            min(TOURNAMENT_SIZE, len(indexed))
        )

        winner = max(
            contestants,
            key=lambda x: x[0]
        )

        parents.append(winner[1])

    return parents


# ─────────────────────────────────────────────
# 8. CROSSOVER
# ─────────────────────────────────────────────

def crossover(parent_a, parent_b):

    if len(parent_a) <= 1:
        return (
            copy.deepcopy(parent_a),
            copy.deepcopy(parent_b)
        )

    cut = random.randint(
        1,
        len(parent_a) - 1
    )

    child_a = (
        parent_a[:cut]
        + parent_b[cut:]
    )

    child_b = (
        parent_b[:cut]
        + parent_a[cut:]
    )

    return child_a, child_b


# ─────────────────────────────────────────────
# 9. MUTATION
# ─────────────────────────────────────────────

def mutate(
    individual,
    netlist,
    nodes,
    mutation_rate
):

    mutated = copy.deepcopy(individual)

    for i, (
        gi,
        port,
        signal,
        fake_signal,
        key_bit
    ) in enumerate(mutated):

        if random.random() < mutation_rate:

            choice = random.randint(0, 1)

            if choice == 0:

                fake_signal = random.choice(nodes)

                while (
                    fake_signal == signal
                    or is_constant(fake_signal)
                ):
                    fake_signal = random.choice(nodes)

            else:
                key_bit ^= 1

            mutated[i] = (
                gi,
                port,
                signal,
                fake_signal,
                key_bit
            )

    return mutated


# ─────────────────────────────────────────────
# 10. GENETIC ALGORITHM
# ─────────────────────────────────────────────

def run_genetic_algorithm(
    netlist,
    graph,
    nodes
):

    print(f"\n{'='*55}")
    print(
        f"  AutoLock GA  |  "
        f"Pop={POPULATION_SIZE}  "
        f"Gen={NUM_GENERATIONS}  "
        f"Key={KEY_LENGTH}"
    )
    print(f"{'='*55}\n")

    population = generate_initial_population(
        netlist,
        nodes,
        KEY_LENGTH,
        POPULATION_SIZE
    )

    history = []

    best_individual = None
    best_fitness_seen = -1.0

    for gen in range(NUM_GENERATIONS):

        fitnesses = [
            compute_fitness(ind, graph, nodes)
            for ind in population
        ]

        gen_best = max(fitnesses)
        gen_avg = sum(fitnesses) / len(fitnesses)

        history.append(
            (gen_best, gen_avg)
        )

        best_idx = fitnesses.index(gen_best)

        if gen_best > best_fitness_seen:

            best_fitness_seen = gen_best

            best_individual = copy.deepcopy(
                population[best_idx]
            )

        if (gen + 1) % 10 == 0 or gen == 0:

            print(
                f"Gen {gen+1:>3}/{NUM_GENERATIONS} | "
                f"Best: {gen_best:.4f} | "
                f"Avg: {gen_avg:.4f}"
            )

        parents = select_parents(
            population,
            fitnesses,
            POPULATION_SIZE
        )

        new_population = []

        new_population.append(
            copy.deepcopy(
                population[best_idx]
            )
        )

        while len(new_population) < POPULATION_SIZE:

            pa, pb = random.sample(parents, 2)

            if random.random() < CROSSOVER_RATE:

                child_a, child_b = crossover(pa, pb)

            else:

                child_a = copy.deepcopy(pa)
                child_b = copy.deepcopy(pb)

            child_a = mutate(
                child_a,
                netlist,
                nodes,
                MUTATION_RATE
            )

            child_b = mutate(
                child_b,
                netlist,
                nodes,
                MUTATION_RATE
            )

            new_population.append(child_a)

            if len(new_population) < POPULATION_SIZE:
                new_population.append(child_b)

        population = new_population

    print(
        f"\nRe-evaluating champion over "
        f"{_ATTACK_TRIALS_FINAL} trials..."
    )

    best_fitness_final = compute_fitness(
        best_individual,
        graph,
        nodes,
        n_trials=_ATTACK_TRIALS_FINAL
    )

    return (
        best_individual,
        best_fitness_final,
        history
    )


# ─────────────────────────────────────────────
# 11. VERILOG OUTPUT
# ─────────────────────────────────────────────

def format_locked_verilog(
    netlist,
    locked
):

    lines = []

    mod = netlist.get(
        'module',
        'locked_circuit'
    )

    key = locked.get('key', [])
    lps = locked.get('locking_points', [])

    lines.append(
        "// AutoLock-generated locked netlist"
    )

    lines.append(
        f"// Correct key: {key}"
    )

    lines.append(
        f"module {mod}_locked ("
    )

    lines.append(
        f"    input wire [{len(key)-1}:0] key,"
    )

    if netlist['inputs']:
        lines.append(
            "    input wire "
            + ", ".join(netlist['inputs'])
            + ","
        )

    if netlist['outputs']:
        lines.append(
            "    output wire "
            + ", ".join(netlist['outputs'])
        )

    lines.append(");")
    lines.append("")

    wire_list = list(dict.fromkeys([
        w for w in locked['wires']
        if w not in netlist['outputs']
    ]))

    if wire_list:

        lines.append(
            "    wire "
            + ", ".join(wire_list)
            + ";"
        )

        lines.append("")

    lines.append(
        "    // Original gates"
    )

    for g in locked['gates']:

        port_str = ", ".join(
            f".{p}({n})"
            for p, n in g['ports'].items()
        )

        lines.append(
            f"    {g['type']} "
            f"{g['name']} "
            f"({port_str});"
        )

    lines.append("")
    lines.append(
        "    // Locking MUXes"
    )

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


# ─────────────────────────────────────────────
# 12. RESULTS
# ─────────────────────────────────────────────

def print_results(
    netlist,
    best_individual,
    best_fitness,
    history
):

    locked = apply_locking(
        netlist,
        best_individual
    )

    key = locked['key']

    attack_acc = 1.0 - best_fitness

    print(f"\n{'='*55}")
    print("RESULTS")
    print(f"{'='*55}")

    print(
        f"Best Fitness    : "
        f"{best_fitness:.4f}"
    )

    print(
        f"Attack Accuracy : "
        f"{attack_acc:.4f}"
    )

    print(
        f"Key Length      : "
        f"{len(key)} bits"
    )

    print(
        f"Correct Key     : "
        f"{''.join(str(b) for b in key)}"
    )

    print()

    verilog_out = format_locked_verilog(
        netlist,
        locked
    )

    return verilog_out, key


def save_outputs(
    verilog_out,
    key,
    history
):

    with open(
        "best_locked_circuit.v",
        "w"
    ) as f:

        f.write(verilog_out)

    print(
        "\nSaved: best_locked_circuit.v"
    )

    with open(
        "best_key.txt",
        "w"
    ) as f:

        f.write(
            "Correct key (binary): "
            + ''.join(str(b) for b in key)
            + "\n"
        )

        f.write(
            "Key bits: "
            + str(key)
            + "\n"
        )

    print("Saved: best_key.txt")

    if HAS_MATPLOTLIB and history:

        gens = range(
            1,
            len(history) + 1
        )

        bests = [h[0] for h in history]
        avgs = [h[1] for h in history]

        plt.figure(figsize=(9, 4))

        plt.plot(
            gens,
            bests,
            linewidth=2,
            label='Best Fitness'
        )

        plt.plot(
            gens,
            avgs,
            linestyle='--',
            label='Average Fitness'
        )

        plt.xlabel('Generation')
        plt.ylabel('Fitness')

        plt.title(
            'AutoLock GA Fitness'
        )

        plt.legend()

        plt.tight_layout()

        plt.savefig(
            "fitness_history.png",
            dpi=120
        )

        plt.close()

        print(
            "Saved: fitness_history.png"
        )


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():

    if len(sys.argv) > 1:

        verilog_file = sys.argv[1]

        try:

            with open(verilog_file) as f:
                source = f.read()

            print(
                f"Loaded Verilog from: "
                f"{verilog_file}"
            )

        except FileNotFoundError:

            print(
                f"File not found: "
                f"{verilog_file}"
            )

            source = SAMPLE_VERILOG

    else:

        print(
            "No file specified — "
            "using built-in sample."
        )

        source = SAMPLE_VERILOG

    netlist = parse_verilog(source)

    print(
        f"Gates: {len(netlist['gates'])}"
    )

    graph, nodes = build_graph(netlist)

    if not nodes:

        nodes = (
            netlist['inputs']
            + netlist['outputs']
            + netlist['wires']
        )

    if len(nodes) < 2:

        nodes = [f"n{i}" for i in range(20)]

    best_individual, best_fitness, history = (
        run_genetic_algorithm(
            netlist,
            graph,
            nodes
        )
    )

    verilog_out, key = print_results(
        netlist,
        best_individual,
        best_fitness,
        history
    )

    save_outputs(
        verilog_out,
        key,
        history
    )

    print(
        f"\nDone. Final best fitness: "
        f"{best_fitness:.4f}\n"
    )


if __name__ == "__main__":
    main()
