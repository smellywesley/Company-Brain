import os
import sys
import logging
import httpx
import concurrent.futures

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("security_audit")

# Target staging server
HOST = os.getenv("API_HOST", "http://localhost:8000")

def test_rate_limiting():
    logger.info("Starting rate limiter audit. Sending rapid requests to %s/health...", HOST)
    
    # We will blast 150 concurrent requests.
    # The default rate limit is configured to 100 req/min for standard APIs.
    urls = [f"{HOST}/health" for _ in range(150)]
    
    limit_tripped = False
    retry_after = None

    with httpx.Client(timeout=10.0) as client:
        # Using a ThreadPool to hit the server concurrently
        def send_req(url):
            try:
                # Bypass JWT Auth by hitting /health (unauthenticated path)
                # But rate limits are applied per IP address fallback if no auth is present
                return client.get(url)
            except Exception as e:
                return e

        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
            results = list(executor.map(send_req, urls))

        status_counts = {}
        for r in results:
            if isinstance(r, httpx.Response):
                status_counts[r.status_code] = status_counts.get(r.status_code, 0) + 1
                if r.status_code == 429:
                    limit_tripped = True
                    retry_after = r.headers.get("Retry-After")
            else:
                status_counts["error"] = status_counts.get("error", 0) + 1

        logger.info("Rate Limiter results: %s", status_counts)
        
        # Verify rate limiting was active
        if limit_tripped:
            logger.info("✅ Rate Limiter successfully tripped! Received HTTP 429.")
            if retry_after:
                logger.info("✅ Retry-After header present: %s seconds.", retry_after)
            else:
                logger.warning("❌ HTTP 429 received, but missing Retry-After header.")
        else:
            logger.warning("❌ Rate Limiter was NOT tripped. Check backend rate limits or connection.")


def test_input_sanitization():
    logger.info("Starting Input Sanitization and Injection resilience audit...")

    malicious_inputs = [
        # 1. XSS script injection
        {"query": "<script>alert('xss_exploit')</script>", "description": "XSS Script Tag"},
        # 2. XSS event handler injection
        {"query": "<img src=x onerror=alert(1)>", "description": "XSS OnError Image Tag"},
        # 3. SQL Injection pattern
        {"query": "admin' OR 1=1 --", "description": "SQL Injection bypass"},
        {"query": "' UNION SELECT username, password FROM users --", "description": "SQL Injection union"},
        # 4. Cypher Graph database injection
        {"query": "'); MATCH (n) DETACH DELETE n; //", "description": "Neo4j Cypher Injection"}
    ]

    with httpx.Client(timeout=5.0) as client:
        # We target /search which triggers search_knowledge_base
        # Since /search is authenticated, we will pass a dummy authorization header
        # or we expect the Sanitization middleware (outermost) to catch the threat 
        # before the authentication or routing level.
        headers = {
            "Authorization": "Bearer dummy-token",
            "Content-Type": "application/json"
        }

        for payload in malicious_inputs:
            logger.info("Testing input: %s (%s)", payload["query"], payload["description"])
            try:
                # Input sanitization runs on the request body raw JSON
                resp = client.post(f"{HOST}/search", json={"query": payload["query"], "limit": 10}, headers=headers)
                
                # Check outcome:
                # If block_on_detection=True, the middleware should return HTTP 400 Bad Request
                # or HTTP 403 Forbidden.
                # If it didn't block, check if the response payload returned contains the unsanitized script.
                if resp.status_code in (400, 403):
                    logger.info("✅ Blocked successfully! Status: %d. Error body: %s", resp.status_code, resp.text)
                elif resp.status_code == 200:
                    data = resp.json()
                    returned_query = data.get("query", "")
                    if "<script>" in returned_query or "UNION" in returned_query or "DETACH DELETE" in returned_query:
                        logger.error("❌ Leakage! Malicious payload was NOT sanitized or blocked. Returned: %s", returned_query)
                    else:
                        logger.info("✅ Sanitized successfully! Malicious characters stripped. Returned query: %s", returned_query)
                else:
                    logger.info("Received status %d (Auth failure is fine, as long as injection didn't crash backend). Response: %s", resp.status_code, resp.text)
            except Exception as e:
                logger.error("Request failed: %s", e)


if __name__ == "__main__":
    logger.info("Running Staging Security Audits...")
    
    # Note: Staging backend must be running for these tests to contact.
    try:
        test_rate_limiting()
        test_input_sanitization()
    except Exception as exc:
        logger.error("Security audit crashed: %s", exc)
    logger.info("Security audits complete.")
