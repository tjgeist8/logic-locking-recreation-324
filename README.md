# Implementing CAS-Lock and AutoLock for RTL Verilog and Yosys Netlists

## Dependencies 

- Ubuntu 24.04.4 LTS
- Python 3.14.4
- conda 26.1.1
- yosys 0.64
- Matplotlib 3.10.9 (optional, AutoLock can use it)

### To clone environment use these commands
```bash
conda env create -f environment.yml
conda activate logic_design
``` 

## CAS-Lock
The CAS-Lock directory includes the following files
- b20_C.bench
- b20_C.v
- cas_lock_netlist.py
- cas_lock_rtl.py
- synthesis_basic_gates.ys
- sanitize_netlist.py
- verilog_to_bench.py
- NangateOpenCellLibrary_typical.lib
- sld
- lcmp

### Locking an RTL File 
To produce a locked netlist from an unlocked RTL Verilog file.
```bash
python3 cas_lock_rtl.py [input_file.v]
```
Then synthesize the file with yosys.

NOTE: You must edit the synthesis_basic_gates.ys file with the correct
- verilog file name on line 2
- top module name on line 5
- proper output file name on line 44
```bash
yosys synthesis_basic_gates.ys
```
This process will give you a locked, synthesized netlist.

### Locking a Yosys Netlist
To produce a locked netlist you must first synthesize the RTL Verilog

NOTE: You must edit the synthesis_basic_gates.ys file with the correct
- verilog file name on line 2
- top module name on line 5
- proper output file name on line 44
```bash
yosys synthesis_basic_gates.ys
```
Then run this command with your synthesized netlist
```
python3 cas_lock_netlist.py [synthesized_netlist.v]
```
Both scripts include optional modifiers:
-    -o, --output FILE      
-    -n, --num-inputs INT (default: 4)
-    -p, --p-value INT 
-    -s, --seed INT    
-    --target-output STR  
-    --key STR            

### Turning a locked netlist into a testable .bench file
Once you have your locked netlist from either above methods, you need to sanitize the netlist with the command
```bash
python3 sanitize_netlist.py --input [locked_netlist.v] --output [locked_netlist_sanitized.v]
```

Then take that sanitized netlist and turn it into a bench file
```bash
python3 verilog_to_bench --input [locked_netlist_sanitized.v] --output [locked_netlist_sanitized.bench]
```

### Running the SAT Attack
Once you have acquired the locked .bench file, you can run the attack
```bash
./sld [encrypted_bench_file.bench] [original_bench_file.bench]
```
This will display each iteration of the attack and print a correct key to the terminal. To verify that the attack has found a correct key, run the command:
```bash
./lcmp [original_bench_file.bench] [encrypted_bench_file.bench] key=<value>
```
If this command returns "equivalent", the SAT Attack was succesful
## AutoLock 
In the AutoLock directory you will find the following
- Netlist_AutoLock.py
- RTL_AutoLock.py
- NangateOpenCellLibrary_typical.lib
- synthesis_basic_gates.ys
- c432.bench
- c432.v
- c432_basic_gates_syn.v
- locked_verilog_to_bench.py
- locked_netlist_to_bench.py
- sld
- lcmp

### How to edit AutoLock parameters
If you would like to change any of the parameters(population size, generation count, mutation rate, crossover rate, key length, attack trials, or attack trials final) for AutoLock you can do so by editing the file with nano:
```bash
nano Netlist_AutoLock.py
```
or 
```bash
nano RTL_AutoLock.py
```
Once you are in the file scroll down to the first section marked "GLOBAL DEFAULT" and edit the values there if you wish

### How to use AutoLock on a netlist file
If testing with the c432 file that is already in the directory run the this command:
```bash
python3 Netlist_AutoLock.py c432_basic_gates_syn.v
```
If you want to test it with a different file you will need to get a synthesized version of that file in the directory and replace the c432_basic_gates_syn.v with your files name.

The script should print some output for a while and a message letting you know when it is done, you now have a locked netlist that should be named best_locked_netlist.v

If you would like to test your file against a SAT attack you will need to turn your locked file into a .bench file, to do that with the c432 example run this command:
```bash
python3 locked_netlist_to_bench.py --input best_locked_netlist.v --output best_locked_netlist.bench
```
This will return a file called best_locked_netlist.bench you can then run this command to simulate a SAT attack on it:
```bash
./sld best_locked_netlist.bench c432.bench
```
If you are using a file other than the c432 example you will need your files original .bench 
file and you should replace c432.bench with that file

### How to use AutoLock on a RTL Verilog file
If you are testing with the c432 file that is already in the directory run this command:
```bash
python3 RTL_AutoLock.py c432.v
```
If you to test a different file just replace the c432.v with your verilog file

The script should print some output for a while and a message letting you knwo when it is done, you now have a locked RTL file that should be named best_locked_verilog.v

If you would like to test your file against a SAT attack you will need to turn your locked file into a .bench file, to do that with the c432 example run this command next:
```bash
yosys synthesis_basic_gates.ys
```
This will synthesize your locked RTL file, however this line will only work with the c432 example if you are testing your own file you will need to nano into synthesis_basic_gates.ys and change the top module name to match your files
after that you should be able to run this command to convert your synthesized RTL file into a .bench file
```bash
python3 locked_verilog_to_bench.py --input locked_verilog_basic_gates_syn.v --output locked_verilog_basic_gates_syn.bench
```
This will give you a .bench that you can put into the attack with this command:
```bash
./sld locked_verilog_basic_gates_syn.bench c432.bench
```
If you are using your own file you will replace c432.bench with your files original .bench
