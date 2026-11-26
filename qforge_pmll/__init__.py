"""
`qforge_pmll` — Unified Q-Forge × Starlight × HAL × `drQedwards/pmll` Toolkit
=============================================================================
"""
from .ers_certified_reconsider import (
    EPISTEMIC_DEVICE_MEASURED,
    EPISTEMIC_EXACT_CERTIFIED,
    EPISTEMIC_HEURISTIC,
    ERSMemoryBlock,
    ProofCarryingERSEngine,
    verify_drup_proof,
    verify_rational_nullstellensatz,
    verify_rational_spd_certificate,
)
from .gf2_farkas_decoder import (
    decode_noisy_parity_via_farkas_excision,
    solve_gf2_with_farkas_cert,
    verify_farkas_unsat_certificate,
)
from .merkle_anchor import (
    build_directory_merkle_manifest,
    rfc6962_leaf_hash,
    rfc6962_node_hash,
    rfc6962_root_and_audit_path,
    scan_repo_hygiene,
    verify_rfc6962_inclusion,
)
from .silo_fwht import (
    TIER_COLD,
    TIER_HOT,
    TIER_WARM,
    ContractBoundQPromiseRegistry,
    StarlightContractKey,
    UpgradedPMLLSilo,
    canonicalize_3xq_chart_orbit,
    djb2_streaming_u32,
    pmll_legacy_embed_32f,
    qforge_fwht_simhash_128b,
    simhash_angular_cosine,
)

__version__ = "0.173.0"

__all__ = [
    "__version__",
    "TIER_COLD",
    "TIER_WARM",
    "TIER_HOT",
    "EPISTEMIC_HEURISTIC",
    "EPISTEMIC_DEVICE_MEASURED",
    "EPISTEMIC_EXACT_CERTIFIED",
    "djb2_streaming_u32",
    "pmll_legacy_embed_32f",
    "qforge_fwht_simhash_128b",
    "simhash_angular_cosine",
    "UpgradedPMLLSilo",
    "StarlightContractKey",
    "canonicalize_3xq_chart_orbit",
    "ContractBoundQPromiseRegistry",
    "verify_farkas_unsat_certificate",
    "solve_gf2_with_farkas_cert",
    "decode_noisy_parity_via_farkas_excision",
    "verify_drup_proof",
    "verify_rational_spd_certificate",
    "verify_rational_nullstellensatz",
    "ERSMemoryBlock",
    "ProofCarryingERSEngine",
    "rfc6962_leaf_hash",
    "rfc6962_node_hash",
    "rfc6962_root_and_audit_path",
    "verify_rfc6962_inclusion",
    "build_directory_merkle_manifest",
    "scan_repo_hygiene",
]
