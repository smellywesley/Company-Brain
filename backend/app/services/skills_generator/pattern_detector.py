"""
Pattern Detector for Skill Generation.

Uses unsupervised clustering to identify recurring operational tasks
from a batch of document embeddings. Dense clusters represent repeated
patterns (e.g., "handling a refund", "deploying a hotfix") that can
be synthesized into a Skill.
"""

import logging
from typing import NamedTuple

import numpy as np
from sklearn.cluster import AgglomerativeClustering

logger = logging.getLogger(__name__)


class ClusterResult(NamedTuple):
    cluster_id: str
    document_indices: list[int]
    texts: list[str]


class PatternDetector:
    """Clusters document embeddings to find repeating operational patterns."""

    def __init__(
        self, 
        distance_threshold: float = 0.5, 
        min_cluster_size: int = 3
    ) -> None:
        """
        Args:
            distance_threshold: Cosine distance threshold for linking clusters.
            min_cluster_size: Minimum documents required to consider a cluster a "pattern".
        """
        self.distance_threshold = distance_threshold
        self.min_cluster_size = min_cluster_size
        
        # We use Agglomerative Clustering with cosine distance, which works well 
        # for sentence embeddings.
        self.clusterer = AgglomerativeClustering(
            n_clusters=None, 
            metric='cosine', 
            linkage='average',
            distance_threshold=self.distance_threshold
        )

    def detect_clusters(self, texts: list[str], embeddings: list[list[float]]) -> list[ClusterResult]:
        """Run clustering on a batch of documents and return valid patterns.
        
        Args:
            texts: Original document texts.
            embeddings: Corresponding embedding vectors.
            
        Returns:
            List of ClusterResult containing texts that form a pattern.
        """
        if not texts or not embeddings or len(texts) != len(embeddings):
            logger.warning("PatternDetector: Invalid input data length.")
            return []

        if len(texts) < self.min_cluster_size:
            logger.info("PatternDetector: Not enough documents to form a valid cluster.")
            return []

        X = np.array(embeddings)
        
        try:
            labels = self.clusterer.fit_predict(X)
        except Exception as exc:
            logger.error("PatternDetector: Clustering failed: %s", exc)
            return []

        # Group indices by their cluster label
        clusters: dict[int, list[int]] = {}
        for idx, label in enumerate(labels):
            if label == -1: # Noise (if we were using DBSCAN/HDBSCAN)
                continue
            clusters.setdefault(label, []).append(idx)

        valid_clusters = []
        for label, indices in clusters.items():
            if len(indices) >= self.min_cluster_size:
                cluster_texts = [texts[i] for i in indices]
                valid_clusters.append(ClusterResult(
                    cluster_id=f"cluster_{label}",
                    document_indices=indices,
                    texts=cluster_texts
                ))

        logger.info(
            "PatternDetector: Found %d valid patterns from %d documents.", 
            len(valid_clusters), len(texts)
        )
        return valid_clusters
