# cuda/

- `cuda_pmll_v2.cu` — `sm_86` tiered salience kernel. Compile with
  `nvcc -O3 -arch=sm_86 --fmad=false`. Running the binary requires one
  registered GPU lease and a ≥1536 MiB reserve (see
  `scripts/gpu_lease_run.sh`). Do not retry after a native fault.
- `j1j2_otf_prefix_kernels.cu` — on-the-fly J1–J2 prefix kernel (research).
- `v168_shor_cyclic_kickmix_sm86.cu` — classical Shor-phase simulator
  (`QPU=false`, `clay_proof=0`). No quantum credit.

`make -f Makefile.pmll cuda-sm86` compiles only and refuses an un-leased run.
