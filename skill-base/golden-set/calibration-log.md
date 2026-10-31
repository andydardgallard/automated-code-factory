# Reviewer calibration log — the append-only record of `references/code-review.md` §7

`calibrate_reviewer.py score --log <this file>` appends ONE `calibration:` line per calibration;
`calibrate_reviewer.py status` reads the LAST one and fails loudly when a calibration is due — the
reviewer prompt changed since it, or `5` runs were recorded since it. The line is data, not prose:

`calibration: run_id=<id|-> prompt_sha256=<64 hex> runs=<journal run count at calibration> review_runs=<review-typed subset> verdict_accuracy=<matched>/<total> accuracy=<percent> macro_precision=<0.000>`

The log is append-only: a record is never edited or removed, so the history of what the reviewer was
calibrated against stays readable. A repository with no record yet has never discharged the
obligation — `status` says so and exits 1.

calibration: run_id=20261026-2ea2eb55 prompt_sha256=a77413b0786597a4aa9b093c151b251058405ec118b2dd81eacc46651c44286e runs=31 review_runs=8 verdict_accuracy=7/7 accuracy=100.0% macro_precision=1.000
calibration: run_id=20261026-838dc245 prompt_sha256=40473b916eeee05361e805d8f0ae0a6c5b623fb6f06d6d21a5923c93813b809b runs=32 review_runs=8 verdict_accuracy=7/7 accuracy=100.0% macro_precision=1.000
calibration: run_id=20261031-6dfd0921 prompt_sha256=6087dd7a9b46c1079f3f7986d050344372ef8bb10cd60f162a4208b17cc0751d runs=33 review_runs=8 verdict_accuracy=7/7 accuracy=100.0% macro_precision=1.000
calibration: run_id=20261031-dd7ffa0e prompt_sha256=6087dd7a9b46c1079f3f7986d050344372ef8bb10cd60f162a4208b17cc0751d runs=34 review_runs=9 verdict_accuracy=7/7 accuracy=100.0% macro_precision=1.000
