import argparse
import threading
import webbrowser

from .server import make_server


def main():
    parser = argparse.ArgumentParser(prog="jiji", description="Jiji — calcul de moyennes scolaires")
    parser.add_argument("--db", default="jiji.db", help="fichier de base de données (défaut : jiji.db)")
    parser.add_argument("--host", default="127.0.0.1", help="adresse d'écoute (0.0.0.0 pour le réseau local)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="ne pas ouvrir le navigateur")
    args = parser.parse_args()
    server = make_server(args.db, args.host, args.port)
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    print(f"Jiji démarré sur {url}  (base : {args.db})  —  Ctrl+C pour arrêter")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
