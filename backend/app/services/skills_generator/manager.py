"""
Skill Generator Manager.

Orchestrates the entire skill generation lifecycle:
1. Pulls documents and embeddings
2. Scans for adversarial prompt injections
3. Detects patterns via clustering
4. Synthesizes skills via LLM
5. Signs the definition (HMAC-SHA256)
6. Simulates against historical data
7. Applies auto-activation logic based on risk/confidence/simulation
8. Persists to the database
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkflowRun
from app.db.repositories.skill_repo import SkillRepo
from app.schemas.skill import SkillGenerateRequest
from app.services.security.prompt_injection import AdversarialDetector, DetectionResult
from app.services.security.skill_signing import SkillSigner
from app.services.security.skill_simulator import SkillSimulator
from app.services.skills_generator.pattern_detector import PatternDetector
from app.services.skills_generator.synthesizer import SkillSynthesizer

logger = logging.getLogger(__name__)


class SkillManager:
    def __init__(
        self,
        db_session: AsyncSession,
        synthesizer: SkillSynthesizer,
        pattern_detector: PatternDetector,
        adversarial_detector: AdversarialDetector,
    ) -> None:
        self.session = db_session
        self.repo = SkillRepo(db_session)
        self.synthesizer = synthesizer
        self.pattern_detector = pattern_detector
        self.adversarial_detector = adversarial_detector
        self.signer = SkillSigner()
        self.simulator = SkillSimulator()

    async def run_discovery_pipeline(
        self, tenant_id: uuid.UUID, documents: list[dict[str, Any]]
    ) -> int:
        """Run the full discovery pipeline on a batch of documents."""
        logger.info("SkillManager: Starting discovery pipeline for tenant %s with %d documents", tenant_id, len(documents))

        texts = [doc.get("text", "") for doc in documents]
        embeddings = [doc.get("embedding", []) for doc in documents]

        clusters = self.pattern_detector.detect_clusters(texts, embeddings)
        if not clusters:
            logger.info("SkillManager: No patterns detected.")
            return 0

        skills_generated = 0

        for cluster in clusters:
            logger.info("SkillManager: Processing cluster %s with %d documents", cluster.cluster_id, len(cluster.texts))

            # Security scan
            is_safe = True
            for text in cluster.texts:
                scan_result: DetectionResult = await self.adversarial_detector.scan_text(text)
                if scan_result.is_malicious:
                    logger.warning(
                        "SkillManager: Cluster %s rejected — adversarial injection: %s",
                        cluster.cluster_id, scan_result.reason,
                    )
                    is_safe = False
                    break
            if not is_safe:
                continue

            # Synthesize
            req = SkillGenerateRequest(
                cluster_id=cluster.cluster_id,
                document_contents=cluster.texts,
                tenant_id=str(tenant_id),
            )
            response = await self.synthesizer.synthesize(req)
            if not response:
                logger.warning("SkillManager: Synthesizer failed for cluster %s", cluster.cluster_id)
                continue

            definition_dict = response.definition.model_dump()

            # Sign the definition
            signature = self.signer.sign(definition_dict)

            # Auto-activation gate
            target_status = "draft"
            if response.risk_level == "low" and response.confidence_score >= 0.90:
                # Must also pass simulation against historical runs
                stmt = select(WorkflowRun).where(
                    WorkflowRun.tenant_id == tenant_id
                ).order_by(WorkflowRun.created_at.desc()).limit(50)
                result = await self.session.execute(stmt)
                historical = result.scalars().all()

                history_dicts = [
                    {
                        "trigger_data": r.trigger_data,
                        "final_action": r.final_action,
                        "status": r.status,
                        "critic_approved": r.critic_approved,
                    }
                    for r in historical
                ]

                sim_result = self.simulator.simulate(definition_dict, history_dicts)
                if sim_result.passed:
                    target_status = "active"
                    logger.info(
                        "SkillManager: Auto-activating '%s' (conf=%.2f, sim=%.0f%%)",
                        response.definition.name, response.confidence_score, sim_result.pass_rate * 100,
                    )
                else:
                    logger.info(
                        "SkillManager: Simulation failed for '%s' (%.0f%%) — keeping as draft",
                        response.definition.name, sim_result.pass_rate * 100,
                    )
            else:
                logger.info(
                    "SkillManager: Skill '%s' needs review (risk=%s, conf=%.2f)",
                    response.definition.name, response.risk_level, response.confidence_score,
                )

            # Persist
            slug = response.definition.name.lower().replace(" ", "-")[:127]
            existing = await self.repo.get_by_slug(tenant_id, slug)
            if existing:
                logger.info("SkillManager: Skill '%s' already exists. Skipping.", slug)
                continue

            await self.repo.create_skill(
                tenant_id=tenant_id,
                slug=slug,
                name=response.definition.name,
                description=response.definition.description,
                definition=definition_dict,
                status=target_status,
                risk_level=response.risk_level,
                confidence_score=response.confidence_score,
                discovered_from=[f"cluster_{cluster.cluster_id}"],
                created_by="system",
                signature=signature,
            )
            skills_generated += 1

        return skills_generated
