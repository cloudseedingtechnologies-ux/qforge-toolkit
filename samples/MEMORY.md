# Sample lab memory

This file is a scrubbed, generic example. It is not a real lab log.

## [2026-11-01] speedgate-rule
type: note
tags: policy, speedgate

A candidate is adopted only if it is exact and at least 10% faster on the complete task, with at least three paired repeats at the same thread count. Otherwise it is staged, or rejected if it is not exact.

## [2026-11-02] seal-pipeline
type: note
tags: seal, receipt

A sealed archive is a copy, never the live tree. Home prefixes are replaced with ~, a leak scan must pass, then MANIFEST and SHA256SUMS are packed. A receipt is taken from a fresh extract, not the retained one.

## [2026-11-03] temple-inertia
type: note
tags: checker, certificate

Eigenvalue claims that are meant to be certified use two exact checkers: Sylvester inertia (LDL with 1-by-1 and 2-by-2 pivots, two pivot orders must agree) and Temple's inequality (a lower bound mu - r^2/(zeta - mu) when zeta > mu). Residual disks enclose an eigenvalue only for normal matrices.

## [2026-11-04] claim-linter
type: note
tags: linter, receipt

Prose and receipt claims are scanned for unbounded strength words. A hit is allowed when the same sentence limits the claim. not_claimed fields are never scanned.
