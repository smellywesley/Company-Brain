"""
Concurrency regression tests.

These guard the two shared-state fixes that the in-memory implementations
depend on under real multi-threaded request load:

1. Rate limiter token bucket — without a lock, concurrent requests can both
   observe ``tokens >= 1.0`` and both subtract, over-granting or driving the
   count negative (rate limit silently bypassed).
2. Audit logger HMAC chain — without a lock, two concurrent entries can read
   the same ``_prev_hmac`` and break the tamper-evident chain.
"""

import threading


class TestRateLimiterConcurrency:
    """The token bucket must grant at most `max_tokens` under concurrent load."""

    def test_no_overgrant_under_threads(self):
        from app.middleware.rate_limiter import _Bucket

        # 100 tokens, refill disabled for a deterministic count.
        bucket = _Bucket(tokens=100.0, max_tokens=100, refill_rate=0.0)
        results: list[bool] = []
        append_lock = threading.Lock()

        def worker() -> None:
            ok = bucket.consume()
            with append_lock:
                results.append(ok)

        threads = [threading.Thread(target=worker) for _ in range(200)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sum(results) == 100, f"expected exactly 100 grants, got {sum(results)}"
        assert bucket.tokens >= 0, f"tokens went negative: {bucket.tokens}"


class TestAuditChainConcurrency:
    """The HMAC chain must stay linked (no shared _prev_hmac) under threads."""

    def test_chain_links_uniquely(self, tmp_path, monkeypatch):
        import app.middleware.audit_logger as al

        # Redirect the log file to a temp path and reset chain state.
        log_file = tmp_path / "audit.jsonl"
        monkeypatch.setattr(al, "_AUDIT_LOG_FILE", log_file)
        monkeypatch.setattr(al, "_AUDIT_LOG_DIR", tmp_path)
        monkeypatch.setattr(al, "_last_hmac", "GENESIS")

        def worker(i: int) -> None:
            al._write_entry({"type": "test", "seq": i})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        import json

        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 100, f"expected 100 entries, got {len(lines)}"

        entries = [json.loads(ln) for ln in lines]
        prev_hmacs = [e["_prev_hmac"] for e in entries]
        chain_hmacs = [e["_chain_hmac"] for e in entries]

        # Every _prev_hmac must be unique — a shared value means two entries
        # raced on the same chain head.
        assert len(set(prev_hmacs)) == len(prev_hmacs), "duplicate _prev_hmac — chain raced"
        # Every chain hmac is unique too.
        assert len(set(chain_hmacs)) == len(chain_hmacs), "duplicate _chain_hmac"
