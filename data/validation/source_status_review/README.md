# Frozen/live table-status reconciliation

Three measurement tables in the frozen 311-table audit carry `verified` in the
production map but `review` in later verifier run files. This evidence bundle
resolves whether their frozen outcomes remain supported by the patent sources.

| Patent and XML table | Printed table | Measurements | Disposition |
|---|---|---:|---|
| US20210038631A1:1 (IRF4) | Table 1 | 69 | Retain; source values and sequences agree |
| US20240026353A1:16 (SCN2A) | Table 5 | 78 | Retain; source values and sequences agree |
| US20240026353A1:18 (SCN2A) | Table 7 | 78 | Retain; source values and sequences agree |

Source XML table numbers and printed captions differ in the SCN2A patent. The
comparison retains dagger-marked compound IDs and excludes continuation rows
containing only additional target sites. Negative inhibition values remain valid:
inhibition is `100 - percent control`, without clipping.

All 225 source measurements agree exactly with the frozen Gold ledger. All 225
live sequences and outcomes agree with the independently read source cells.
Dose, cell line and target identity agree as well. No frozen outcome, audit
denominator or release measurement was changed.

The live files contain extraction-run messages and July 26 extraction timestamps.
The verifier's `extract` and `rerun-with-comment` handlers unconditionally write
`status: review` and remove the signed-off CSV. Their only listed problem here is
the informational single-dose/export label. No status-transition log survives:
rerunning explains how this state can arise, but the exact historical action
cannot be asserted. The frozen map's label is not evidence of a new human sign-off.

The `.xml` files freeze the actual table and relevant preceding source paragraphs.
The `.json` files freeze live rows and provenance metadata without executing their
extraction scripts. `manifest.json` records hashes of the original files and each
snapshot. Source and live paths are provenance only; the check needs no external
workspace. Run `just audit-source-status` to regenerate
`data/results/source_status_review.json`; it is also part of `just audit`.

This resolves retention of these tables in the outcome audit. It does not sign
off their full chemistry/context extraction: sugar/backbone fields and the
approximately 24-hour treatment period remain blank in the live rows. Those
fields stay in the separate chemistry/context review. Live verifier states are
left intact so a measurement-only check does not grant broader approval.

The remaining 12 live review runs are IRF4 XML Tables 111–114, 119–122,
125–126 and 129–130. None occurs in the frozen Gold ledger. Their source captions
state reduction of **cell proliferation** in KMS11, H929, U2932, TMD8, Karpas299
or SupM2 cells. These are not measurements of target-RNA knockdown, and are outside
the efficacy endpoint definition used by this audit. Their table XML is frozen
here, and the check verifies their absence from the audit and the proliferation
caption. Their current live classification as `inhibition` should not silently
bring them into a later target-knockdown audit.
