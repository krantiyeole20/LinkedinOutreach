from sentence_transformers import SentenceTransformer, util
import numpy as np
from typing import Tuple
from enum import Enum

import structlog

logger = structlog.get_logger()

class ReactionType(Enum):
    LIKE = "Like"
    CELEBRATE = "Celebrate"
    SUPPORT = "Support"
    LOVE = "Love"
    INSIGHTFUL = "Insightful"
    FUNNY = "Funny"

REACTION_CATEGORIES = {
    ReactionType.CELEBRATE: [
        "congratulations on the new job",
        "excited to announce promotion",
        "achieved milestone reached goal",
        "celebrating success anniversary",
        "new role new position",
        "thrilled to share good news",
        "award recognition achievement",
        "graduation completed certification",
        "company milestone funding round"
    ],
    ReactionType.SUPPORT: [
        "going through difficult time",
        "facing challenges struggling",
        "layoff job search unemployment",
        "mental health awareness",
        "seeking advice need help",
        "dealing with setback failure",
        "support needed tough times",
        "grief loss mourning",
        "health issues recovery"
    ],
    ReactionType.LOVE: [
        "inspiring story motivation",
        "passion dedication commitment",
        "heartwarming touching story",
        "giving back charity volunteer",
        "family personal milestone",
        "grateful thankful appreciation",
        "beautiful moment captured",
        "love what I do passion"
    ],
    ReactionType.INSIGHTFUL: [
        "industry insights trends",
        "learned lesson experience",
        "data analysis research findings",
        "thought leadership opinion",
        "tips advice recommendations",
        "strategy framework methodology",
        "case study analysis",
        "market trends predictions",
        "technical deep dive explanation"
    ],
    ReactionType.FUNNY: [
        "funny story humor joke",
        "meme hilarious laughing",
        "workplace humor office jokes",
        "friday mood weekend vibes",
        "relatable content sarcasm",
        "plot twist unexpected ending",
        "tech humor developer jokes"
    ]
}

class ReactionAnalyzer:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        logger.info("loading_sentence_transformer", model=model_name)
        self.model = SentenceTransformer(model_name)
        self._build_category_embeddings()
    
    def _build_category_embeddings(self):
        self.category_embeddings = {}
        
        for reaction_type, phrases in REACTION_CATEGORIES.items():
            embeddings = self.model.encode(phrases, convert_to_tensor=True)
            self.category_embeddings[reaction_type] = embeddings
        
        logger.info("category_embeddings_built", categories=len(self.category_embeddings))
    
    def analyze(self, post_content: str, confidence_threshold: float = 0.5) -> Tuple[ReactionType, float]:
        if not post_content or len(post_content.strip()) < 10:
            logger.info("content_too_short_defaulting_to_like")
            return ReactionType.LIKE, 0.0
        
        post_embedding = self.model.encode(post_content, convert_to_tensor=True)
        
        best_reaction = ReactionType.LIKE
        best_score = 0.0
        
        scores = {}
        
        for reaction_type, category_embeddings in self.category_embeddings.items():
            similarities = util.cos_sim(post_embedding, category_embeddings)
            max_similarity = float(similarities.max())
            avg_similarity = float(similarities.mean())
            
            combined_score = 0.7 * max_similarity + 0.3 * avg_similarity
            scores[reaction_type.value] = round(combined_score, 3)
            
            if combined_score > best_score:
                best_score = combined_score
                best_reaction = reaction_type
        
        logger.debug("reaction_scores", scores=scores, selected=best_reaction.value)
        
        if best_score < confidence_threshold:
            logger.info("low_confidence_defaulting_to_like", 
                       best_score=best_score, threshold=confidence_threshold)
            return ReactionType.LIKE, best_score
        
        return best_reaction, best_score


_analyzer_instance = None

def get_analyzer() -> ReactionAnalyzer:
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = ReactionAnalyzer()
    return _analyzer_instance

def test_analyzer():
    analyzer = get_analyzer()
    
    test_cases = [
        "Excited to announce I've just been promoted to Senior Manager!",
        "Going through a tough time after being laid off last week.",
        "Here are 5 tips for better productivity I learned this year.",
        "When you realize it's only Tuesday... #MondayMood",
        "Feeling grateful for this amazing team I get to work with.",
    ]
    
    print("\n" + "="*60)
    print("REACTION ANALYZER TEST")
    print("="*60)
    
    for content in test_cases:
        reaction, confidence = analyzer.analyze(content)
        print(f"\nContent: {content[:50]}...")
        print(f"Reaction: {reaction.value} (confidence: {confidence:.2f})")
    
    print("\n" + "="*60)
