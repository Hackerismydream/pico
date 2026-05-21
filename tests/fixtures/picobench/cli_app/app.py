import argparse


def build_parser():
    parser = argparse.ArgumentParser(prog="picocli")
    parser.add_argument("name")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return f"hello {args.name}"
