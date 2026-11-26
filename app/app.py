"""Tiny demo app: writes JSON logs (stdout + file) and exposes Prometheus metrics. No dependencies."""
import json, os, random, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP = os.environ.get("APP_NAME", "app")
LOG_FILE = os.environ.get("LOG_FILE", f"/logs/{APP}.log")
BUCKETS = [0.05, 0.1, 0.25, 0.5, 1.0, 2.5]

lock = threading.Lock()
requests = {}                      # status -> count
bucket_counts = [0] * len(BUCKETS)  # non-cumulative
hist_sum, hist_count = 0.0, 0

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logf = open(LOG_FILE, "a", buffering=1)


def log(level, msg, **kw):
    line = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "level": level,
                       "app": APP, "msg": msg, **kw})
    print(line, flush=True)
    logf.write(line + "\n")


def simulate():
    global hist_sum, hist_count
    while True:
        dur = random.expovariate(1 / 0.15)
        status = random.choices(["200", "404", "500"], [88, 4, 8])[0]
        with lock:
            requests[status] = requests.get(status, 0) + 1
            hist_sum += dur
            hist_count += 1
            for i, b in enumerate(BUCKETS):
                if dur <= b:
                    bucket_counts[i] += 1
                    break
        level = "ERROR" if status == "500" else "WARN" if status == "404" else "INFO"
        log(level, "request handled", status=int(status), duration_ms=round(dur * 1000),
            path=random.choice(["/order", "/pay", "/refund"]))
        time.sleep(random.uniform(0.1, 0.5))


def render():
    out = ["# HELP app_requests_total Total requests.", "# TYPE app_requests_total counter"]
    with lock:
        for s, c in sorted(requests.items()):
            out.append(f'app_requests_total{{app="{APP}",status="{s}"}} {c}')
        out += ["# HELP app_request_duration_seconds Request latency.",
                "# TYPE app_request_duration_seconds histogram"]
        cum = 0
        for b, c in zip(BUCKETS, bucket_counts):
            cum += c
            out.append(f'app_request_duration_seconds_bucket{{app="{APP}",le="{b}"}} {cum}')
        out.append(f'app_request_duration_seconds_bucket{{app="{APP}",le="+Inf"}} {hist_count}')
        out.append(f'app_request_duration_seconds_sum{{app="{APP}"}} {hist_sum}')
        out.append(f'app_request_duration_seconds_count{{app="{APP}"}} {hist_count}')
    return "\n".join(out) + "\n"


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = render().encode() if self.path == "/metrics" else b"ok\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=simulate, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
