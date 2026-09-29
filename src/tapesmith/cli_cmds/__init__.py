"""Paket für CLI-Befehlsmodule.

Jedes Modul (Name ohne führenden Unterstrich, nicht `base`) definiert `COMMAND: str`,
`HELP: str`, `register(parser: argparse.ArgumentParser) -> None` und
`run(args: argparse.Namespace, ctx: CliContext) -> int`.
"""
