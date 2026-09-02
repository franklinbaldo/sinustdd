---
type: Spec
title: SinusTddEvidence
description: Contract for causal phase witnesses emitted by Sinos.
---

# SinusTddEvidence

`SinusTddEvidence` is the authored OKF concept used for durable causal phase witnesses.

The common scalar frontmatter is intentionally relational: `schema_version`, `cycle_id`,
`phase`, `repository_ref`, and optional `previous_evidence_digest`. Phase-specific witness
facts such as passed/failed tests, fingerprints, intent, and reflections remain ordinary OKF
frontmatter fields and may include lists or mappings.

Version 2 does not embed a JSON payload in the Markdown body and does not store a self-hash.
Its chain points to the previous document's OKF `parsed_digest`, computed by `okf-parser`.
The Markdown body is for human-readable explanation only.

The adjacent declared schema provides stable DuckDB types for the common causal projection.
Bundle-level `okf.schema.sql` requires `(cycle_id, phase)` to be unique. Sinos then combines
that relational evidence with Git ancestry to prove `BASELINE <= RED <= GREEN <= HEAD`.
