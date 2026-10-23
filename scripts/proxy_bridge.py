"""Lightweight TCP bridge to forward traffic to local proxy."""
import socket
import threading

def forward(src, dst):
    try:
        while data := src.recv(65536):
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            src.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass

def handle(client):
    try:
        remote = socket.create_connection(("127.0.0.1", 10808))
    except Exception:
        client.close()
        return
    threading.Thread(target=forward, args=(client, remote), daemon=True).start()
    threading.Thread(target=forward, args=(remote, client), daemon=True).start()

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", 10809))
    server.listen(128)
    print("Proxy bridge listening on 0.0.0.0:10809 -> 127.0.0.1:10808", flush=True)
    while True:
        client, _ = server.accept()
        threading.Thread(target=handle, args=(client,), daemon=True).start()

if __name__ == "__main__":
    main()

