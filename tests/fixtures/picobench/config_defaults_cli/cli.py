import argparse

from config import load_defaults


def build_config(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--retries", type=int)
    args = parser.parse_args(argv)
    config = load_defaults()
    if args.timeout is not None:
        config["timeout"] = args.timeout
    if args.retries is not None:
        config["retries"] = args.retries
    return config
