import socket
import sys


def _port_in_use(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def main():
    args = sys.argv[1:]

    if args and args[0] in ("--web", "-w", "web"):
        import uvicorn
        from allspark.web_ui import create_app
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
            print(f"❌ Port {port} is already in use.")
            for alt in range(8001, 8020):
                if not _port_in_use(alt, host):
                    port = alt
                    print(f"🔄 Switching to port {port}")
                    break
            else:
                print("❌ No available port found in 8000-8019 range.")
                sys.exit(1)

        app = create_app(db_path)
        print(f"🔥 AllSpark Web UI starting at http://{host}:{port}")
        uvicorn.run(app, host=host, port=port)
    else:
        from allspark.cli import SparkCLI
        db_path = args[0] if args and not args[0].startswith("-") else None
        cli = SparkCLI(db_path)
        cli.run()


if __name__ == "__main__":
    main()
