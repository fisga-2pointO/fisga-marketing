import http.server
import socketserver
import os

PORT = int(os.environ.get("PORT", 8080))


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Clean URLs: serve /early-access from early-access.html, etc.
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        # /promo → permanent server-side redirect to the main site
        if path.rstrip("/") == "/promo":
            self.send_response(301)
            self.send_header("Location", "https://fisga.co")
            self.end_headers()
            return
        if path != "/" and not os.path.splitext(path)[1]:
            candidate = path.lstrip("/") + ".html"
            if os.path.isfile(candidate):
                self.path = "/" + candidate
        return super().do_GET()


with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"Serving on port {PORT}")
    httpd.serve_forever()
