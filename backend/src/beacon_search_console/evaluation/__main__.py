"""CLI de evaluación:

    python -m beacon_search_console.evaluation run --dataset scifact \\
        --systems bm25,bm25+ltr-qrels --output eval/results/scifact.json
    python -m beacon_search_console.evaluation check \\
        --report eval/results/ci.json --baseline eval/baselines/ci.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from beacon_search_console.evaluation.runner import (
    SYSTEM_NAMES,
    EvaluationConfig,
    check_against_baseline,
    run_evaluation,
)

# backend/src/beacon_search_console/evaluation/__main__.py -> raíz del repo
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m beacon_search_console.evaluation")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="evalúa uno o varios sistemas sobre una colección BEIR")
    run.add_argument("--dataset", required=True)
    run.add_argument("--systems", default="bm25", help=f"separados por comas: {SYSTEM_NAMES}")
    run.add_argument("--max-queries", type=int, default=None)
    run.add_argument("--ltr-train-max-queries", type=int, default=1000)
    run.add_argument("--data-dir", type=Path, default=_REPO_ROOT / "eval" / "data")
    run.add_argument("--work-dir", type=Path, default=_REPO_ROOT / "eval" / "work")
    run.add_argument("--output", type=Path, required=True)

    check = sub.add_parser("check", help="falla si alguna métrica baja respecto a la base")
    check.add_argument("--report", type=Path, required=True)
    check.add_argument("--baseline", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)

    if args.command == "run":
        systems = tuple(name.strip() for name in str(args.systems).split(",") if name.strip())
        config = EvaluationConfig(
            dataset=args.dataset,
            data_dir=args.data_dir,
            work_dir=args.work_dir,
            systems=systems,
            max_queries=args.max_queries,
            ltr_train_max_queries=args.ltr_train_max_queries,
        )
        report = run_evaluation(config)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", "utf-8")
        for result in report["results"]:
            metrics = result["metrics"]
            print(
                f"{report['dataset']:<9} {result['system']:<20} "
                f"nDCG@10={metrics['ndcg_at_10']:.4f} MRR@10={metrics['mrr_at_10']:.4f} "
                f"R@100={metrics['recall_at_100']:.4f} ({result['queries_per_second']} q/s)"
            )
        return 0

    report = json.loads(args.report.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    failures = check_against_baseline(report, baseline, float(baseline.get("tolerance", 0.005)))
    if failures:
        for failure in failures:
            print(f"REGRESIÓN: {failure}", file=sys.stderr)
        return 1
    print("sin regresiones frente a la base")
    return 0


if __name__ == "__main__":
    sys.exit(main())
