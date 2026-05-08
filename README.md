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

## AutoLock 
in the AutoLock directory you will find the following
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
if you would like to change any of the parameters(population size, generation count, mutation rate, crossover rate, key length, attack trials, or attack trials final) for AutoLock you can do so by editing the file with nano:
```bash
nano Netlist_AutoLock.py
```
or 
```bash
nano RTL_AutoLock.py
```
once you are in the file scroll down to the first section marked "GLOBAL DEFAULT" and edit the values there if you wish

### How to use AutoLock on a netlist file
if testing with the c432 file that is already in the directory run the this command:
```bash
python3 Netlist_AutoLock.py c432_basic_gates_syn.v
```
if you want to test it with a different file you will need to get a synthesized version of that file in the directory and replace the c432_basic_gates_syn.v with your files name.

the script should print some output for a while and a message letting you know when it is done, you now have a locked netlist that should be named best_locked_netlist.v

if you would like to test your file against a SAT attack you will need to turn your locked file into a .bench file, to do that with the c432 example run this command:
```bash
python3 locked_netlist_to_bench.py --input best_locked_netlist.v --output best_locked_netlist.bench
```
this will return a file called best_locked_netlist.bench you can then run this command to simulate a SAT attack on it:
```bash
./sld best_locked_netlist.bench c432.bench
```
if you are using a file other than the c432 example you will need your files original .bench 
file and you should replace c432.bench with that file

### How to use AutoLock on a RTL Verilog file
if you are testing with the c432 file that is already in the directory run this command:
```bash
python3 RTL_AutoLock.py c432.v
```
if you to test a different file just replace the c432.v with your verilog file

the script should print some output for a while and a message letting you knwo when it is done, you now have a locked RTL file that should be named best_locked_verilog.v

if you would like to test your file against a SAT attack you will need to turn your locked file into a .bench file, to do that with the c432 example run this command next:
```bash
yosys synthesis_basic_gates.ys
```
this will synthesize your locked RTL file, however this line will only work with the c432 example if you are testing your own file you will need to nano into synthesis_basic_gates.ys and change the top module name to match your files
after that you should be able to run this command to convert your synthesized RTL file into a .bench file
```bash
python3 locked_verilog_to_bench.py --input locked_verilog_basic_gates_syn.v --output locked_verilog_basic_gates_syn.bench
```
this will give you a .bench that you can put into the attack with this command:
```bash
./sld locked_verilog_basic_gates_syn.bench c432.bench
```
if you are using your own file you will replace c432.bench with your files original .bench
