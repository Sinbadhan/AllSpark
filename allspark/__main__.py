import argparse
import logging
import socket
import sys

import uvicorn

from allspark import __version__
from allspark.adapters.web_ui import create_app
from allspark.core.i18n import t

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="allspark",
        description="AllSpark — offline AI survival system",
    )
    parser.add_argument("db_path", nargs="?", help="Path to the SQLite database file")
    parser.add_argument("--version", action="version", version=f"AllSpark {__version__}")
    parser.add_argument("--web", "-w", action="store_true", help="Start the Web UI instead of the CLI")
    parser.add_argument("--host", "-H", default="127.0.0.1", help="Web UI bind host (default: 127.0.0.1)")
    parser.add_argument("--port", "-p", type=int, default=8000, help="Web UI bind port (default: 8000)")
    parser.add_argument("--web-token", dest="web_token", default=None,
                        help="Bearer token for /api/* when binding non-loopback (auto-generated if omitted)")
    parser.add_argument("--db", dest="db_override", help="Path to the SQLite database file")
    return parser


def _resolve_args(argv: list[str] | None = None) -> argparse.Namespace:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "web":
        argv[0] = "--web"
    args = _build_parser().parse_args(argv)
    if args.db_override:
        args.db_path = args.db_override
    return args


def main(argv: list[str] | None = None):
    _configure_logging()
    args = _resolve_args(argv)

    if args.web:
        host = args.host
        port = args.port
        db_path = args.db_path

        if host == "0.0.0.0":
            logger.warning("Web UI is binding to 0.0.0.0; only do this on a trusted local network.")

        # Non-loopback binding requires bearer-token auth on /api/* (audit H3).
        # Auto-generate a token if none provided; the Web UI receives it via the
        # HTML template and patches fetch to include the header automatically.
        web_token = None
        if host not in ("127.0.0.1", "localhost", "::1"):
            import secrets as _secrets
            web_token = args.web_token or _secrets.token_urlsafe(32)
            logger.warning(
                "Bearer token auth ENABLED for /api/*. Token: %s "
                "(pass via Authorization: Bearer <token>)", web_token,
            )

        if _port_in_use(port, host):
            logger.warning(t("web_port_in_use", port=port))
            for alt in range(8001, 8020):
                if not _port_in_use(alt, host):
                    port = alt
                    logger.info(t("web_switching_port", port=port))
                    break
            else:
                logger.error(t("web_no_port"))
                sys.exit(1)

        app = create_app(db_path, token=web_token)
        logger.info(t("web_starting", host=host, port=port))
        uvicorn.run(app, host=host, port=port)
    else:
        from allspark.adapters.cli import SparkCLI
        cli = SparkCLI(args.db_path)
        cli.run()


if __name__ == "__main__":
    main()
