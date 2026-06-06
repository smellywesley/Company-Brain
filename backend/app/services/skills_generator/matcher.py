"""
Skill Matcher.

Retrieves the most relevant active skill for a given trigger
using embedding similarity. Prevents context window bloat by only
injecting the specific relevant SkillDefinition into the agent.
"""

import logging
from typing import Any

from app.db.models import Skill
from ingestion.embedding_pipeline import Embedder

logger = logging.getLogger(__name__)

class SkillMatcher:
    """Matches trigger data to the most relevant active Skill."""
    
    def __init__(self, embedder: Embedder | None = None) -> None:
        # We reuse the ingestion embedder for consistency in the vector space
        self.embedder = embedder or Embedder()

    def match_skill(
        self, 
        trigger_data: dict[str, Any], 
        active_skills: list[Skill],
        threshold: float = 0.6
    ) -> Skill | None:
        """Find the best matching skill for the trigger.
        
        Args:
            trigger_data: The input event (e.g., a Slack message or webhook payload)
            active_skills: List of active Skill records from the DB
            threshold: Minimum cosine similarity required to match
            
        Returns:
            The best matching Skill, or None if no skill is relevant enough.
        """
        if not active_skills:
            return None
            
        # Extract a summary from the trigger to embed
        # Fallbacks to ensure we have meaningful text
        text_to_embed = trigger_data.get("summary") or trigger_data.get("text") or str(trigger_data)
        if len(text_to_embed) > 1000:
            text_to_embed = text_to_embed[:1000]
            
        trigger_embedding = self.embedder.embed([text_to_embed])[0]
        
        best_skill = None
        best_score = -1.0
        
        for skill in active_skills:
            # We embed the skill's description and trigger keywords to match against
            keywords = skill.definition.get("trigger_keywords", [])
            desc = skill.definition.get("description", "")
            skill_text = f"{desc} {' '.join(keywords)}"
            
            skill_embedding = self.embedder.embed([skill_text])[0]
            
            # Cosine similarity
            import numpy as np
            score = np.dot(trigger_embedding, skill_embedding) / (
                np.linalg.norm(trigger_embedding) * np.linalg.norm(skill_embedding)
            )
            
            if score > best_score:
                best_score = score
                best_skill = skill
                
        if best_score >= threshold:
            logger.info("SkillMatcher: Matched trigger to skill '%s' (score: %.2f)", best_skill.slug, best_score)
            return best_skill
            
        logger.info("SkillMatcher: No skill matched threshold (best score: %.2f)", best_score)
        return None
