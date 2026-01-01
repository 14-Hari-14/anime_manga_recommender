from typing import List, Dict, Any, Set

class ReRanker:
    def __init__(self):
        # Weights (Sum ~ 1.0)
        self.weights = {
            "vector": 0.5,         # Semantic match (Most important)
            "rating": 0.2,         # Quality
            "popularity": 0.1,     # Fame
            "soft_tag_match": 0.2  # Bonus for matching Genres/Demographics/Soft Limits
        }

    # normalizing score between 0 and 1 so that different scales don't skew results
    def normalize_score(self, value, min_val, max_val):
        if value is None:
            return 0.0
        if max_val == min_val:
            return 0.5
        return (value - min_val) / (max_val - min_val)

    def ranker(self, candidates: List[Dict[str, Any]], hard_filters: Set[str], banned_filters: Set[str], soft_filters: Set[str]) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        # Calculate bounds for normalization
        scores = [c.get('average_score', 0) or 0 for c in candidates]
        pops = [c.get('popularity', 0) or 0 for c in candidates]
        
        min_score, max_score = (min(scores), max(scores)) if scores else (0, 10)
        min_pop, max_pop = (min(pops), max(pops)) if pops else (0, 100)

        for item in candidates:
            # Prepare Item Tags (Tags + Genres combined)
            item_tags_raw = set(item.get('tags', []) + item.get('genres', []))
            item_tags = {t.strip().lower() for t in item_tags_raw}

            
            # enforcing hard filters to disqualify items missing any must-have tags
            if hard_filters:
                if not hard_filters.issubset(item_tags):
                    item['rerank_score'] = -1.0 # Disqualified
                    continue
            # enforcing banned filters to disqualify items containing any banned tags
            if banned_filters:
                if banned_filters.intersection(item_tags):
                    item['rerank_score'] = -1.0 # Disqualified
                    continue

            # penalizing or rewarding based on soft tag matches
            if not soft_filters:
                tag_score = 0.5 # Neutral
            else:
                matches = len(soft_filters.intersection(item_tags))
                total_soft = len(soft_filters)
                tag_score = matches / total_soft

            # calculating the individual scores
            raw_dist = item['faiss_distance']
            # semantic similarity score is how similar vectors are 0 is perfect match, 2 is no match 
            # we invert and clamp to [0,1] to get a similarity score
            vec_score = max(0, 1 - (raw_dist / 2)) 
            
            rating_score = self.normalize_score(item.get('average_score'), min_score, max_score)
            pop_score = self.normalize_score(item.get('popularity'), min_pop, max_pop)

            # Weighted Sum
            final_score = (
                (vec_score * self.weights['vector']) +
                (rating_score * self.weights['rating']) +
                (pop_score * self.weights['popularity']) +
                (tag_score * self.weights['soft_tag_match'])
            )

            item['rerank_score'] = final_score

        # Sort descending
        candidates.sort(key=lambda x: x['rerank_score'], reverse=True)
        
        return candidates