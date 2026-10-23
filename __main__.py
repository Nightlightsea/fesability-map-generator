"""CLI entry point: python -m feasibility_map [options]

Examples (run from the project root):
  python -m feasibility_map                    all maps, using caches
  python -m feasibility_map --only LHR,comb    just two maps (+ clean twins)
  python -m feasibility_map --recompute        rebuild fields + pieces
  python -m feasibility_map --no-basemap       skip the Esri background layer
  python -m feasibility_map --data my.json     alternate points file
  python -m feasibility_map -o test            outputs into ./test/ instead of figures/
  python -m feasibility_map --run-tests tests  batch: one output folder per tests/*.json
"""
import argparse
import sys

from . import pipeline, settings


def build_parser():
    parser = argparse.ArgumentParser(
        prog="feasibility_map",
        description="Render residence-feasibility field maps from points.json.")
    parser.add_argument("--data", default=settings.DEFAULT_DATA,
                        help="points file to use (default: %(default)s)")
    parser.add_argument("--recompute", action="store_true",
                        help="ignore cached fields/pieces and rebuild them")
    parser.add_argument("--rebuild-graph", action="store_true",
                        help="rebuild the road graph even if tiles are unchanged")
    parser.add_argument("--only", default="",
                        help="comma-separated map keys to render "
                             "(scene keys and/or comb)")
    parser.add_argument("--no-basemap", action="store_true",
                        help="do not fetch the Esri basemap (use cache if any)")
    parser.add_argument("-o", "--outdir", metavar="DIR",
                        help="write the PNGs, per-figure reports and the run "
                             "log to DIR (created if needed; relative paths "
                             "resolve against the points file's folder) "
                             "instead of figures/ and cache/report.txt")
    parser.add_argument("--run-tests", metavar="FOLDER", dest="run_tests",
                        help="treat every FOLDER/*.json as a partial override "
                             "of the base points file (--data), run them all, "
                             "and write each test's outputs to its own folder: "
                             "FOLDER/<name>/ (or OUTDIR/<name>/ when -o is "
                             "given); other flags apply to every test")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.run_tests:
        return pipeline.run_tests(args)
    return pipeline.run(args)


if __name__ == "__main__":
    sys.exit(main())
