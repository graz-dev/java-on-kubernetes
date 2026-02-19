#!/usr/bin/env python3
"""CLI entrypoint for scenario generation.

Usage:
    python generate.py <preset_name> [--output-dir DIR] [--seed N]
    python generate.py --list
"""

import argparse

from scenariogen import PRESETS, run_preset


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a load-test scenario.")
    parser.add_argument("preset", nargs="?", help="Preset name (see --list)")
    parser.add_argument("--list", action="store_true", help="List available presets")
    parser.add_argument("--output-dir", default="output", help="Output directory (default: output)")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    parser.add_argument("--configmap-name", default="test-scenario", help="ConfigMap metadata.name")
    parser.add_argument("--namespace", default="microservices-demo", help="ConfigMap metadata.namespace")
    args = parser.parse_args()

    if args.list:
        for name, cfg in PRESETS.items():
            print(f"  {name:15s}  type={cfg['type']}")
        return

    if not args.preset:
        parser.error("preset name required (use --list to see available presets)")

    if args.preset not in PRESETS:
        parser.error(f"unknown preset '{args.preset}' (use --list to see available presets)")

    run_preset(
        args.preset,
        output_dir=args.output_dir,
        seed=args.seed,
        configmap_name=args.configmap_name,
        namespace=args.namespace,
    )


if __name__ == "__main__":
    main()
