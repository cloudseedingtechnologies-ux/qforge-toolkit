"""Exact, pure-standard-library kernels (K1-K7), each with planted-error traps.

K1 exact_synth  minimum circuit size (MCSP / MCSP*) by CDCL; smaller sizes refuted by RUP proofs
                that the independent checker in cdcl.check_rup_proof verifies
K2 fwht_sharpsat exact integer Walsh-Hadamard #SAT for THR o XOR
K3 certified_residual  CG with exact rational error bounds (LDL^T certificate of sigma)
K4 lightcone    exact light-cone closure for Z / ZZ with rational orthogonal gates
K5 detcert      determinantal-representation certificate checker (Grenet per_n)
K6 sat_phase    measured random 3-SAT sweep, every answer checked
K7 flats_fast   affine-flat enumeration over GF(2)^n

Finite experiments only: no hardness, P vs NP or quantum claim. Run all: python -m qforge_toolkit kernels
"""
