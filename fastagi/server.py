import socketserver


class FastAGIHandler(socketserver.StreamRequestHandler):
    def handle(self):
        agi_env = {}
        while True:
            line = self.rfile.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                break
            if ":" in line:
                key, value = line.split(":", 1)
                agi_env[key.strip()] = value.strip()

        self.wfile.write(b'VERBOSE "Dialyra FastAGI connected" 1\n')
        self.wfile.write(b"HANGUP\n")


if __name__ == "__main__":
    with socketserver.ThreadingTCPServer(("0.0.0.0", 4573), FastAGIHandler) as server:
        server.serve_forever()
