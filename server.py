import http.server
import socketserver
import os

PORT = int(os.environ.get("PORT", 8080))
SITE = "https://www.fisga.co"

# Permanent redirects: old address → new address
REDIRECTS = {
    "/promo": SITE + "/",
    "/case-study-go-to-market-pricing-porsche-912.html": "/case-studies/go-to-market-pricing-porsche-912",
    "/case-study-cpg-segmentation-electrodog-usa.html": "/case-studies/cpg-segmentation-electrodog-usa",
    "/case-study-plant-based-verdant-foods-launch.html": "/case-studies/plant-based-verdant-foods-launch",
    "/case-study-concept-testing-nhmu-traveling-exhibition.html": "/case-studies/concept-testing-nhmu-traveling-exhibition",
    "/case-study-concept-testing-card-dial-rewards.html": "/case-studies/concept-testing-card-dial-rewards",
}

# Only these file types are public. Source, config and SQL files are not.
PUBLIC_EXT = {
    ".html", ".txt", ".xml", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".ico", ".mp4", ".webm", ".css", ".js", ".woff", ".woff2", ".pdf",
}
PRIVATE_DIRS = ("/scripts/",)


class Handler(http.server.SimpleHTTPRequestHandler):
    def route(self):
        """Resolve self.path to a file. Returns False if a response was already sent."""
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        query = self.path[len(path):]

        target = REDIRECTS.get(path) or REDIRECTS.get(path.rstrip("/"))
        if target:
            return self.redirect(target + ("" if target.startswith("http") else query))
        # Canonical URLs have no trailing slash: /learn/ → /learn
        if path != "/" and path.endswith("/"):
            return self.redirect(path.rstrip("/") + query)

        if path.startswith("/.") or "/." in path or path.startswith(PRIVATE_DIRS):
            return self.not_found()

        local = path.lstrip("/")
        ext = os.path.splitext(path)[1].lower()
        if path == "/":
            return True
        if not ext:
            # Clean URLs: /early-access → early-access.html, /learn → learn/index.html
            if os.path.isfile(local + ".html"):
                self.path = "/" + local + ".html"
                return True
            if os.path.isfile(os.path.join(local, "index.html")):
                self.path = "/" + local + "/index.html"
                return True
            return self.not_found()
        if ext not in PUBLIC_EXT:
            return self.not_found()
        return True

    def redirect(self, location):
        self.send_response(301)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def not_found(self):
        self.send_error(404, "Not Found")
        return False

    def list_directory(self, path):
        self.send_error(404, "Not Found")
        return None

    def do_GET(self):
        if self.route():
            return super().do_GET()

    def do_HEAD(self):
        if self.route():
            return super().do_HEAD()


socketserver.ThreadingTCPServer.allow_reuse_address = True
socketserver.ThreadingTCPServer.daemon_threads = True
# Threaded: one slow client (e.g. a video download) must not block everyone else
with socketserver.ThreadingTCPServer(("", PORT), Handler) as httpd:
    print(f"Serving on port {PORT}")
    httpd.serve_forever()
