import logging
import socket
import sys

from allspark.core.i18n import t

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _port_in_use(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def main():
    _configure_logging()
    args = sys.argv[1:]

    if args and args[0] in ("--web", "-w", "web"):
        import uvicorn

        from allspark.adapters.web_ui import create_app
        db_path = None
        host = "0.0.0.0"
        port = 8000
        i = 1
        while i < len(args):
            a = args[i]
            if a in ("--host", "-h") and i + 1 < len(args):
                host = args[i + 1]
                i += 2
            elif a in ("--port", "-p") and i + 1 < len(args):
                port = int(args[i + 1])
                i += 2
            elif not a.startswith("-"):
                db_path = a
                i += 1
            else:
                i += 1

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

        app = create_app(db_path)
        logger.info(t("web_starting", host=host, port=port))
        uvicorn.run(app, host=host, port=port)
    else:
        from allspark.adapters.cli import SparkCLI
        db_path = args[0] if args and not args[0].startswith("-") else None
        cli = SparkCLI(db_path)
        cli.run()


if __name__ == "__main__":
    main()
