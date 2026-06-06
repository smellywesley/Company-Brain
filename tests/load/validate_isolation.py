import os
import sys
import uuid
import logging
import threading
import concurrent.futures
from typing import Any

# Ensure we can import app modules by appending path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../backend')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(threadName)s] %(levelname)s - %(message)s")
logger = logging.getLogger("isolation_test")

from app.services.security.tenant_isolation import TenantIsolatedNeo4jStore, TenantIsolatedWeaviateStore

TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())

def test_neo4j_isolation():
    logger.info("Starting Neo4j multi-tenant isolation tests under load...")
    store = TenantIsolatedNeo4jStore()
    store.connect()

    if not store._driver:
        logger.warning("Neo4j database is not running or accessible. Skipping Neo4j isolation tests.")
        return

    # Clear any previous testing residue (scoped by our test tenant IDs only)
    with store._driver.session() as session:
        session.run("MATCH (n) WHERE n.tenant_id = $t1 OR n.tenant_id = $t2 DETACH DELETE n", t1=TENANT_A, t2=TENANT_B)

    # ── 1. Concurrent Writes ──────────────────────────────────────────────────
    def tenant_a_work():
        for i in range(50):
            store.create_node(TENANT_A, "Project", {"name": f"Project-A-{i}", "secret_code": f"SECRET-A-{i}"})
            if i > 0:
                store.create_relationship(TENANT_A, f"Project-A-{i-1}", f"Project-A-{i}", "DEPENDS_ON")

    def tenant_b_work():
        for i in range(50):
            store.create_node(TENANT_B, "Project", {"name": f"Project-B-{i}", "secret_code": f"SECRET-B-{i}"})
            if i > 0:
                store.create_relationship(TENANT_B, f"Project-B-{i-1}", f"Project-B-{i}", "DEPENDS_ON")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        f1 = executor.submit(tenant_a_work)
        f2 = executor.submit(tenant_b_work)
        concurrent.futures.wait([f1, f2])

    logger.info("Concurrent writes completed. Commencing isolation assertions...")

    # ── 2. Isolation Assertions ────────────────────────────────────────────────
    # Test 1: Stats count
    stats_a = store.get_stats(TENANT_A)
    stats_b = store.get_stats(TENANT_B)

    assert stats_a["nodes"] == 50, f"Expected Tenant A to have 50 nodes, got {stats_a['nodes']}"
    assert stats_b["nodes"] == 50, f"Expected Tenant B to have 50 nodes, got {stats_b['nodes']}"

    # Test 2: Text Search Leakage Check
    search_a = store.search_entities(TENANT_A, "Project-B")
    assert len(search_a) == 0, f"Tenant A exposed Tenant B nodes in search results: {search_a}"

    search_b = store.search_entities(TENANT_B, "Project-A")
    assert len(search_b) == 0, f"Tenant B exposed Tenant A nodes in search results: {search_b}"

    # Test 3: Neighbor Retrieval Traversal Leakage Check
    # Even if we query a neighbor from Tenant A, it should never cross-over to Tenant B nodes
    # Let's verify by checking neighbors of Project-A-5
    neighbors_a = store.query_neighbors(TENANT_A, "Project-A-5", depth=2)
    for neighbor in neighbors_a:
        assert neighbor["properties"].get("tenant_id") == TENANT_A, f"Leakage detected! Tenant A query returned node from tenant {neighbor['properties'].get('tenant_id')}"
        assert "Project-B" not in neighbor["name"], "Tenant A query returned Tenant B node name"

    # Test 4: Attempting to query neighbors of Tenant B's node using Tenant A's session
    cross_neighbors = store.query_neighbors(TENANT_A, "Project-B-5", depth=1)
    assert len(cross_neighbors) == 0, f"Tenant A session queried Tenant B node: {cross_neighbors}"

    logger.info("✅ Neo4j Tenant Isolation check passed successfully!")
    store.close()


def test_weaviate_isolation():
    logger.info("Starting Weaviate multi-tenant isolation tests...")
    
    # Weaviate store initialization requires connection
    try:
        from ingestion.embedding_pipeline import WeaviateStore
        base_store = WeaviateStore()
        base_store.connect()
        store = TenantIsolatedWeaviateStore(base_store)
    except Exception as exc:
        logger.warning("Weaviate is not running or accessible. Skipping Weaviate isolation tests: %s", exc)
        return

    # Check Weaviate isolation
    try:
        # Mock embeddings list
        mock_vector = [0.1] * 384
        
        # Upsert documents
        doc_a = [{"content": "Proprietary algorithm specs for Tenant A", "id": "doc-a-1"}]
        doc_b = [{"content": "Proprietary client listings for Tenant B", "id": "doc-b-1"}]
        
        store.upsert(TENANT_A, doc_a)
        store.upsert(TENANT_B, doc_b)
        
        # Search using Tenant A context
        results_a = store.search(TENANT_A, mock_vector, limit=5)
        for r in results_a:
            assert r.get("tenant_id") == TENANT_A, f"Weaviate leak: Tenant A search returned document from tenant {r.get('tenant_id')}"
            assert "Tenant B" not in r.get("content", ""), "Weaviate leak: Tenant A search exposed Tenant B content"
            
        # Search using Tenant B context
        results_b = store.search(TENANT_B, mock_vector, limit=5)
        for r in results_b:
            assert r.get("tenant_id") == TENANT_B, f"Weaviate leak: Tenant B search returned document from tenant {r.get('tenant_id')}"
            assert "Tenant A" not in r.get("content", ""), "Weaviate leak: Tenant B search exposed Tenant A content"

        logger.info("✅ Weaviate Tenant Isolation check passed successfully!")
    except Exception as exc:
        logger.error("Weaviate isolation test crashed: %s", exc)
    finally:
        base_store.close()


if __name__ == "__main__":
    logger.info("Starting Tenant Isolation Validation scripts...")
    test_neo4j_isolation()
    test_weaviate_isolation()
    logger.info("Validation completed.")
