from collections import defaultdict
from threading import Lock


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self._duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self._duration_count: dict[tuple[str, str], int] = defaultdict(int)

    def record_request(self, method: str, path: str, status_code: int, duration: float) -> None:
        route = self._normalize_path(path)
        key = (method.upper(), route, status_code)
        duration_key = (method.upper(), route)
        with self._lock:
            self._requests[key] += 1
            self._duration_sum[duration_key] += duration
            self._duration_count[duration_key] += 1

    def render_prometheus(self) -> str:
        lines = [
            "# HELP contract_ai_requests_total Total HTTP requests.",
            "# TYPE contract_ai_requests_total counter",
        ]
        with self._lock:
            for (method, path, status), count in sorted(self._requests.items()):
                lines.append(
                    'contract_ai_requests_total{'
                    f'method="{method}",path="{path}",status="{status}"'
                    f"}} {count}"
                )
            lines.extend(
                [
                    "# HELP contract_ai_request_duration_seconds Request duration in seconds.",
                    "# TYPE contract_ai_request_duration_seconds summary",
                ]
            )
            for (method, path), total in sorted(self._duration_sum.items()):
                count = self._duration_count[(method, path)]
                labels = f'method="{method}",path="{path}"'
                lines.append(
                    f'contract_ai_request_duration_seconds_sum{{{labels}}} {total:.6f}'
                )
                lines.append(f'contract_ai_request_duration_seconds_count{{{labels}}} {count}')
        return "\n".join(lines) + "\n"

    def _normalize_path(self, path: str) -> str:
        if path.startswith("/contracts/") and "/clauses" in path:
            return "/contracts/{contract_id}/clauses"
        if path.startswith("/contracts/") and "/risks" in path:
            return "/contracts/{contract_id}/risks"
        if path.startswith("/contracts/") and "/ask" in path:
            return "/contracts/{contract_id}/ask"
        if path.startswith("/contracts/") and path.count("/") == 2:
            return "/contracts/{contract_id}"
        if path.startswith("/jobs/"):
            return "/jobs/{job_id}"
        return path


metrics_registry = MetricsRegistry()
