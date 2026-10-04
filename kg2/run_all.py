"""Rebuild TBI-BiomarkerKG v2 end to end. Every step is idempotent (clear-then-write).

    cd kg2 && python3 run_all.py            # full build, ~4 min with a warm cache
Human validation sheets (p6_validation_sheets.py) are NOT regenerated here: re-sampling after
annotators start would invalidate the gold set.
"""
import p0_freeze
import p1_ids
import p2_reference
import p3_omics
import p4_literature
import p5_integrate
import p6_timesplit
import p7_release

for step in (p0_freeze, p1_ids, p2_reference, p3_omics, p4_literature, p5_integrate, p6_timesplit, p7_release):
    print(f"\n=== {step.__name__} ===")
    step.main()
