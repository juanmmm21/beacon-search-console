"""CLI de la consola.

- sin subcomando (o `console`): la consola original sobre el clúster de
  shards (`app.py`), como siempre;
- `docs`: el buscador público de documentación (`docs_app.py`), que lee el
  bundle de `BEACON_DOCS_BUNDLE_ROOT`;
- `mcp`: el servidor MCP del buscador de documentación por stdio, para un
  agente en la misma máquina.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from pathlib import Path

import uvicorn


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beacon-search-console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("console", help="Consola sobre el clúster de shards (por defecto)")
    docs = sub.add_parser("docs", help="Buscador público de documentación")
    docs.add_argument("--bundle-root", type=Path, default=None)
    mcp = sub.add_parser("mcp", help="Servidor MCP del buscador de documentación por stdio")
    mcp.add_argument("--bundle-root", type=Path, required=True)
    mcp.add_argument("--hybrid", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    if args.command == "docs":
        if args.bundle_root is not None:
            os.environ["BEACON_DOCS_BUNDLE_ROOT"] = str(args.bundle_root)
        uvicorn.run(
            "beacon_search_console.docs_app:create_docs_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
        return
    if args.command == "mcp":
        _run_stdio_mcp(args.bundle_root, hybrid=args.hybrid)
        return
    uvicorn.run("beacon_search_console.app:app", host=args.host, port=args.port, reload=args.reload)


def _run_stdio_mcp(bundle_root: Path, *, hybrid: bool) -> None:
    from beacon_search_console.docs_app import DocsConfig, _load_models
    from beacon_search_console.mcp_server import build_mcp_server
    from beacon_search_console.vertical import VerticalSearchService

    models = _load_models(DocsConfig(bundle_root=bundle_root, hybrid=hybrid))
    service = VerticalSearchService(bundle_root, models=models)
    try:
        build_mcp_server(lambda: service).run(transport="stdio")
    finally:
        service.close()


if __name__ == "__main__":
    main()
