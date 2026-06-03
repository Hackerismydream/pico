import argparse


def build_parser():
    parser = argparse.ArgumentParser(prog="tool")
    subcommands = parser.add_subparsers(dest="command", required=True)
    hello = subcommands.add_parser("hello")
    hello.add_argument("name")
    return parser
