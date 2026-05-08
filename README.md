# Implementing CAS-Lock and AutoLock for RTL Verilog and Yosys Netlists

## Dependencies 

- Ubuntu 24.04.4 LTS
- Python 3.14.4
- conda 26.1.1
- yosys 0.64
- Matplotlib 3.10.9 (optional, AutoLock can use it)

### to clone environment use these commands
```bash
conda env create -f environment.yml
conda activate logic_design
``` 

## AutoLock 
in the AutoLock directory you will find the two AutoLock scripts, the NangateOpenCellLibrary, a yosys basic gates synthesis file, and a testfile called c432 in its bench, RTL, and Netlist versions.
