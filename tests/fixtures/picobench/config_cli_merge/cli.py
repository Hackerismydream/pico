import argparse
from config import resolve_timeout


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--timeout", type=int)
    return parser.parse_args(argv)


def main(argv, env):
    args = parse_args(argv)
    return resolve_timeout(args.config, env, args.timeout)
