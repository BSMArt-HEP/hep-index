"""Command-line interface (CONTRACT.md §cli): add/remove/list/reindex/serve/query.

Exit codes: 0 ok, 1 usage/ValueError/FileNotFoundError, 2 KeyError (unknown
codebase). Errors print "error: <msg>" to stderr.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import shutil
import sys
from pathlib import Path

from . import catalog, fetch, indexer, registry
from .recipes import RECIPES
from . import server
from .server import create_mcp_server, list_codebases_impl

# `hep-index query <tool>`: the read-only MCP tools, same impls, JSON out —
# for agents/harnesses without MCP (e.g. skills calling it from a shell).
QUERY_TOOLS = {
    "list_codebases": server.list_codebases_impl,
    "search_code": server.search_code_impl,
    "find_symbol": server.find_symbol_impl,
    "read_file": server.read_file_impl,
    "outline": server.outline_impl,
    "call_graph": server.call_graph_impl,
    "config_keys": server.config_keys_impl,
    "data_files": server.data_files_impl,
}


class _UsageError(Exception):
    """argparse usage problem; contract exit code is 1, not argparse's 2."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise _UsageError(message)


def _split_selector(selector: str) -> tuple[str, str | None]:
    name, _, version = selector.partition("@")
    return name, version or None


def _short_head(head: str | None) -> str:
    return head[:7] if head else "none"


def _cmd_add(args: argparse.Namespace) -> int:
    path = os.path.abspath(os.path.expanduser(args.path))
    exclude = list(args.exclude)
    if args.recipe:
        exclude += RECIPES[args.recipe]  # recipe EXTENDS explicit --exclude
    entry = registry.CodebaseEntry(name=args.name, version=args.version,
                                   path=path, exclude=exclude)
    registry.add_entry(entry)
    stats = indexer.build_index(entry)
    print(f"registered {entry.id}: {stats.n_files} files, "
          f"{stats.n_symbols} symbols, head {_short_head(stats.git_head)}")
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    name, version = _split_selector(args.selector)
    for entry in registry.remove_entry(name, version):
        shutil.rmtree(registry.index_dir(entry), ignore_errors=True)
        print(f"removed {entry.id}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    infos = list_codebases_impl()
    if args.json:
        print(json.dumps(infos, indent=2))
        return 0
    if not infos:
        print("no codebases registered")
        return 0
    width = max(len(i["id"]) for i in infos)
    for i in infos:
        print(f"{i['id']:<{width}}  {i['path']}  "
              f"files={i['n_files']}  stale={str(i['stale']).lower()}")
    return 0


def _cmd_reindex(args: argparse.Namespace) -> int:
    for entry in registry.resolve(args.selector):
        stats = indexer.build_index(entry)
        print(f"reindexed {entry.id}: {stats.n_files} files, "
              f"{stats.n_symbols} symbols, head {_short_head(stats.git_head)}")
    return 0


def _cmd_catalog(args: argparse.Namespace) -> int:
    cat = catalog.load_catalog()
    if args.category:
        cat = {n: e for n, e in cat.items()
               if e.category == args.category}
    if not cat:
        print("no matching catalog entries")
        return 0
    for entry in cat.values():
        versions = ", ".join(
            v + (" (latest)" if v == entry.versions[-1] else "")
            for v in entry.versions)
        note = entry.notes.splitlines()[0] if entry.notes else ""
        print(f"{entry.name:<13} {entry.category:<18} {entry.type:<8} {versions}")
        if note:
            print(f"{'':<13} note: {note}")
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    name, version = _split_selector(args.selector)
    cat = catalog.load_catalog()
    if name not in cat:
        raise ValueError(f"not in catalog: {name} — run 'hep-index catalog'; "
                         "use CLI add for local paths")
    entry = cat[name]
    version = version or catalog.latest(entry)
    root = (Path(args.root).expanduser() if args.root else
            Path(os.environ.get("HEP_INDEX_ROOT", "~/hep-codebases")).expanduser())
    stats = fetch.fetch_and_register(
        name=name, version=version, kind=entry.type,
        url=catalog.render_url(entry, version),
        extract_root=catalog.render_extract_root(entry, version),
        root=root, recipe=entry.recipe, exclude=list(args.exclude))
    print(f"registered {stats['codebase']}: {stats['n_files']} files, "
          f"{stats['n_symbols']} symbols, head {_short_head(stats['git_head'])}")
    return 0


def _query_value(text: str):
    """JSON when it parses (numbers, true/false/null, lists), else the string."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def _sig(fn) -> str:
    return str(inspect.signature(fn)).replace("'", "")


def _cmd_query(args: argparse.Namespace) -> int:
    if args.tool in (None, "list") or args.tool not in QUERY_TOOLS:
        if args.tool not in (None, "list"):
            print(f"error: unknown tool {args.tool!r}", file=sys.stderr)
        descs = {}
        try:
            descs = {t.name: t.description for t in
                     create_mcp_server()._tool_manager.list_tools()}
        except Exception:
            pass
        for name, fn in QUERY_TOOLS.items():
            first = (descs.get(name) or fn.__doc__ or "").strip().splitlines()
            print(f"{name}{_sig(fn)}\n    {first[0] if first else ''}")
        print("\nusage: hep-index query TOOL [POSITIONAL ...] [param=value ...]"
              "\n       hep-index query TOOL --doc   (full description)")
        return 0 if args.tool in (None, "list") else 1
    fn = QUERY_TOOLS[args.tool]
    if args.help_tool:
        try:
            desc = {t.name: t.description for t in
                    create_mcp_server()._tool_manager.list_tools()}[args.tool]
        except Exception:
            desc = fn.__doc__ or ""
        print(f"{args.tool}{_sig(fn)}\n\n{inspect.cleandoc(desc)}")
        return 0
    params = list(inspect.signature(fn).parameters)
    kwargs: dict = {}
    positional = []
    for a in args.args:
        key, eq, val = a.partition("=")
        if eq and key in params:
            kwargs[key] = _query_value(val)
        else:
            positional.append(a)  # positional values stay strings
    free = [p for p in params if p not in kwargs]
    if len(positional) > len(free):
        raise ValueError(f"too many positional arguments for {args.tool}; "
                         f"parameters: {', '.join(params)}")
    kwargs.update(zip(free, positional))
    print(json.dumps(fn(**kwargs), indent=1, ensure_ascii=False))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    create_mcp_server().run()
    return 0


def _build_parser() -> _Parser:
    parser = _Parser(prog="hep-index",
                     description="Multi-codebase index for HEP software")
    parser.add_argument("--local", action="store_true",
                        help="project-local mode: registry and index cache live "
                             "under ./.hep-index/ (cwd); global paths are never "
                             "read or written. Overrides HEP_INDEX_CONFIG/CACHE.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add", help="register a codebase and build its index")
    p.add_argument("path")
    p.add_argument("--name", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                   help="exclude glob, repeatable")
    p.add_argument("--recipe", choices=sorted(RECIPES), metavar="NAME",
                   help="preset exclude globs, extends --exclude")
    p.set_defaults(func=_cmd_add)

    p = sub.add_parser("remove", help="unregister and drop the index")
    p.add_argument("selector", metavar="name[@version]")
    p.set_defaults(func=_cmd_remove)

    p = sub.add_parser("list", help="list registered codebases")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_list)

    p = sub.add_parser("reindex", help="rebuild the index")
    p.add_argument("selector", metavar="name[@version]")
    p.set_defaults(func=_cmd_reindex)

    p = sub.add_parser("catalog", help="list curated fetchable sources")
    p.add_argument("--category", metavar="CAT",
                   help="filter by category (e.g. me-generator, recast-engine)")
    p.set_defaults(func=_cmd_catalog)

    p = sub.add_parser("fetch", help="fetch a catalog package and index it")
    p.add_argument("selector", metavar="name[@version]")
    p.add_argument("--root", metavar="DIR",
                   help="destination root (default HEP_INDEX_ROOT or ~/hep-codebases)")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                   help="extra exclude glob, repeatable")
    p.set_defaults(func=_cmd_fetch)

    p = sub.add_parser("serve", help="run the MCP server (stdio)")
    p.set_defaults(func=_cmd_serve)

    p = sub.add_parser("query", help="run a read-only MCP tool, print JSON"
                       " (no tool: list them)")
    p.add_argument("tool", nargs="?", metavar="TOOL")
    p.add_argument("args", nargs="*", metavar="ARG",
                   help="positional values, or param=value (JSON-parsed)")
    p.add_argument("--help-tool", "--doc", dest="help_tool", action="store_true",
                   help="print the tool's full description")
    p.set_defaults(func=_cmd_query)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        if argv is None:
            argv = sys.argv[1:]
        if not argv:  # bare invocation: help + registered-coverage footer
            _build_parser().print_help()
            try:
                ids = ", ".join(e.id for e in registry.load_registry()) or "none"
                print(f"\nregistered: {ids} (see 'hep-index list')")
            except Exception:
                pass
            return 0
        args = _build_parser().parse_args(argv)
        if args.local:  # explicit project-local mode (CONTRACT.md §local)
            local_root = Path.cwd() / ".hep-index"
            os.environ["HEP_INDEX_CONFIG"] = str(local_root / "codebases.toml")
            os.environ["HEP_INDEX_CACHE"] = str(local_root / "cache")
        return args.func(args)
    except (_UsageError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyError as exc:
        print(f"error: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 2
