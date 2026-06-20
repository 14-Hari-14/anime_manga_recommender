from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Literal
import faiss
import sqlite3
import numpy as np
from sentence_transformers import SentenceTransformer
import os
import json
import time
import re

from reranking_results import ReRanker
reranker = ReRanker()
# TODO
# 1. Remove cache complexity the benefit is rather small
# 2. Fix popularity binning


# Request Schema (format for data to be recieved)
class RecommendationRequest(BaseModel):
    query: str = Field("", description="Natural language query")
    content_type: List[Literal["anime", "manga", "manhwa", "manhua"]]

    format: List[str] = []
    
    # Overall themes is removed. only use hard tags to enforce must have tags, soft tags to boost scores for prefered tags and banned tags to exclude items with these tags
    hard_limit: List[str] = [] 
    soft_limit: List[str] = []
    banned_tags: List[str] = []
    
    # These are still passed from frontend, so we keep them in schema
    genre: List[str] = []
    viewer_descretion: List[str] = []
    demographic: List[str] = []
    nsfw_allowed: bool = False

    # Score and popularity bounds
    min_score: int = 0
    max_score: int = 100
    min_popularity: int = 0
    max_popularity: int = 99999999

# Response schema (format for data to be sent back)
class RecommendationItem(BaseModel):
    title: str
    description: str | None
    tags: List[str]
    genres: List[str]
    average_score: float | None
    popularity: int | None
    image_url: str | None
    bucket: str | None = None
    relations_chain: List[str] = []
    other_relations: List[str] = []


# Initializing the app as well as the index and db
app = FastAPI(title="Anime / Manga Recommendation API")
EMBEDDING_MODEL = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
UNIFIED_INDEX = faiss.read_index("../data/vector_store/unified_index.faiss")
UNIFIED_DB = sqlite3.connect("../data/recommendations.db", check_same_thread=False)

# check to see if the connections were successful
print("--- DATA HEALTH CHECK ---")
print(f"Unified Index Size: {UNIFIED_INDEX.ntotal} vectors")
print("-------------------------")

# Embed the user query in a faiss index compatible format float32
def embed_query(text: str) -> np.ndarray:
    vec = EMBEDDING_MODEL.encode(text)
    vec = vec.astype("float32")
    vec /= np.linalg.norm(vec) + 1e-12
    return vec.reshape(1, -1)

# Fetch the actual name and details from the database corresponding to the faiss index
def fetch_metadata(ids: List[int], conn: sqlite3.Connection, table: str, buckets: List[str]):
    results = {}
    BATCH_SIZE = 900 # limit is 999 was added if the number of titles requested goes over 999
    cursor = conn.cursor()

    bucket_placeholders = ",".join("?" for _ in buckets)

    for i in range(0, len(ids), BATCH_SIZE):
        batch_ids = ids[i : i + BATCH_SIZE]
        if not batch_ids: continue
        
        placeholders = ",".join("?" for _ in batch_ids)
        
        # gets the data we want from db to display on frontend from the db
        query = f"""
            SELECT faiss_id, title, description, tags, genres, average_score, popularity, image_url, bucket, relations, id
            FROM {table}
            WHERE faiss_id IN ({placeholders}) AND bucket IN ({bucket_placeholders})
        """
        
        cursor.execute(query, batch_ids + buckets)
        rows = cursor.fetchall()
        for row in rows:
            results[row[0]] = row
    return results


# Sanitizes query strings to prevent FTS5 syntax errors and format for OR searches
def sanitize_fts_query(query_str: str) -> str:
    stopwords = {
        "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", 
        "any", "are", "as", "at", "be", "because", "been", "before", "being", "below", 
        "between", "both", "but", "by", "could", "did", "do", "does", "doing", "down", 
        "during", "each", "few", "for", "from", "further", "had", "has", "have", "having", 
        "he", "her", "here", "hers", "herself", "him", "himself", "his", "how", "i", "if", 
        "in", "into", "is", "it", "its", "itself", "me", "more", "most", "my", "myself", 
        "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", 
        "our", "ours", "ourselves", "out", "over", "own", "same", "she", "should", "so", 
        "some", "such", "than", "that", "the", "their", "theirs", "them", "themselves", 
        "then", "there", "these", "they", "this", "those", "through", "to", "too", "under", 
        "until", "up", "very", "was", "we", "were", "what", "when", "where", "which", 
        "while", "who", "whom", "why", "with", "would", "you", "your", "yours", "yourself", 
        "yourselves"
    }
    # Strip out non-alphanumeric/non-space characters
    cleaned = re.sub(r'[^\w\s]', ' ', query_str)
    tokens = [t.strip().lower() for t in cleaned.split() if t.strip()]
    # Filter out stopwords
    filtered_tokens = [t for t in tokens if t not in stopwords]
    if not filtered_tokens:
        # Fallback to unfiltered tokens if all were stopwords to prevent empty query
        filtered_tokens = tokens
    if not filtered_tokens:
        return ""
    # Join with OR so BM25 returns any document containing at least one term
    return " OR ".join(filtered_tokens)


# Fetch metadata by primary DB id instead of faiss_id
def fetch_metadata_by_db_ids(ids: List[int], conn: sqlite3.Connection, table: str, buckets: List[str]):
    results = {}
    BATCH_SIZE = 900
    cursor = conn.cursor()
    bucket_placeholders = ",".join("?" for _ in buckets)

    for i in range(0, len(ids), BATCH_SIZE):
        batch_ids = ids[i : i + BATCH_SIZE]
        if not batch_ids: continue
        placeholders = ",".join("?" for _ in batch_ids)
        query = f"""
            SELECT faiss_id, title, description, tags, genres, average_score, popularity, image_url, bucket, relations, id
            FROM {table}
            WHERE id IN ({placeholders}) AND bucket IN ({bucket_placeholders})
        """
        cursor.execute(query, batch_ids + buckets)
        rows = cursor.fetchall()
        for row in rows:
            results[row[10]] = row  # Key by database id (row[10])
    return results


# Helpers to resolve relations chain dynamically
def get_relations_by_id(conn: sqlite3.Connection, media_id: int) -> tuple[str | None, str | None]:
    cursor = conn.cursor()
    cursor.execute("SELECT relations, title FROM media WHERE id = ?", (media_id,))
    row = cursor.fetchone()
    if row:
        return row[0], row[1]
    return None, None

def resolve_chain(conn: sqlite3.Connection, start_id: int, start_title: str, cache: dict | None = None) -> tuple[List[str], List[str], set]:
    visited = {start_id}
    
    def get_relations_cached(media_id):
        if cache is not None and media_id in cache:
            return cache[media_id]
        res = get_relations_by_id(conn, media_id)
        if cache is not None:
            cache[media_id] = res
        return res
    
    # Traverse prequels (backward)
    prequels = []
    curr_id = start_id
    curr_relations_str, _ = get_relations_cached(curr_id)
    
    while True: # no need to limit depth using for loop visited will handle circular relation
        if not curr_relations_str:
            break
        try:
            relations = json.loads(curr_relations_str)
        except Exception:
            break
            
        prequel_node = None
        for rel in relations:
            if rel.get("relationType") == "PREQUEL":
                node = rel.get("node") or {}
                p_id = node.get("id")
                if p_id and p_id not in visited:
                    prequel_node = node
                    break
        
        if prequel_node:
            p_id = prequel_node["id"]
            p_title_block = prequel_node.get("title") or {}
            p_title = p_title_block.get("english") or p_title_block.get("romaji") or p_title_block.get("native") or "Unknown"
            prequels.append(p_title)
            visited.add(p_id)
            curr_id = p_id
            curr_relations_str, _ = get_relations_cached(curr_id)
        else:
            break
            
    # Reverse prequels to go from oldest to newest
    prequels.reverse()
    
    # Traverse sequels (forward)
    sequels = []
    curr_id = start_id
    curr_relations_str, _ = get_relations_cached(curr_id)
    
    while True: 
        if not curr_relations_str:
            break
        try:
            relations = json.loads(curr_relations_str)
        except Exception:
            break
            
        sequel_node = None
        for rel in relations:
            if rel.get("relationType") == "SEQUEL":
                node = rel.get("node") or {}
                s_id = node.get("id")
                if s_id and s_id not in visited:
                    sequel_node = node
                    break
                    
        if sequel_node:
            s_id = sequel_node["id"]
            s_title_block = sequel_node.get("title") or {}
            s_title = s_title_block.get("english") or s_title_block.get("romaji") or s_title_block.get("native") or "Unknown"
            sequels.append(s_title)
            visited.add(s_id)
            curr_id = s_id
            curr_relations_str, _ = get_relations_cached(curr_id)
        else:
            break
            
    # Extract other relations from the recommended item's relations string
    other_relations = []
    curr_relations_str, _ = get_relations_cached(start_id)
    if curr_relations_str:
        try:
            relations = json.loads(curr_relations_str)
            for rel in relations:
                rel_type = rel.get("relationType", "")
                if rel_type not in ("PREQUEL", "SEQUEL"):
                    node = rel.get("node") or {}
                    title_block = node.get("title") or {}
                    title = title_block.get("english") or title_block.get("romaji") or title_block.get("native") or "Unknown"
                    other_relations.append(f"{rel_type}: {title}")
        except Exception:
            pass

    # Build final chain: older prequels -> start_title -> newer sequels
    relations_chain = []
    if prequels or sequels:
        relations_chain = prequels + [start_title] + sequels

    return relations_chain, other_relations, visited


# Helper to parse tags and genres from SQLite stringified lists safely
def parse_tags_genres(raw_str) -> List[str]:
    if not raw_str or not isinstance(raw_str, str):
        return []
    cleaned = raw_str.replace("[", "").replace("]", "").replace("'", "").replace('"', "")
    return [t.strip() for t in cleaned.split(",") if t.strip()]


# Recommendation Endpoint
@app.post("/recommend", response_model=List[RecommendationItem])
def recommend(req: RecommendationRequest):
    start_time = time.time()
    
    # 1. Embed query (for FAISS)
    query_start = time.time()
    query_vec = embed_query(req.query) if req.query.strip() else None
    query_time = time.time() - query_start
    
    requested_buckets = list(set(req.content_type))
    if not requested_buckets:
        return []

    # If query is present, do hybrid search
    if query_vec is not None:
        # 2. FAISS deep search (top 900 candidates)
        faiss_start = time.time()
        SEARCH_DEPTH = 900
        D, I = UNIFIED_INDEX.search(query_vec, k=SEARCH_DEPTH)
        faiss_time = time.time() - faiss_start
        faiss_ids = [int(idx) for idx in I[0] if idx >= 0]

        # 3. BM25 search via SQLite FTS5 (top 900 candidates)
        fts_start = time.time()
        fts_query = sanitize_fts_query(req.query)
        bm25_ranked_ids = []
        if fts_query:
            cursor = UNIFIED_DB.cursor()
            bucket_placeholders = ",".join("?" for _ in requested_buckets)
            query = f"""
                SELECT f.id 
                FROM media_fts f
                JOIN media m ON f.id = m.id
                WHERE media_fts MATCH ? 
                  AND m.bucket IN ({bucket_placeholders})
                  AND m.average_score >= ? AND m.average_score <= ?
                  AND m.popularity >= ? AND m.popularity <= ?
                ORDER BY bm25(media_fts)
                LIMIT 900
            """
            cursor.execute(query, [fts_query] + requested_buckets + [req.min_score, req.max_score, req.min_popularity, req.max_popularity])
            bm25_ranked_ids = [row[0] for row in cursor.fetchall()]
        fts_time = time.time() - fts_start

        # 4. Map FAISS ids to DB ids (filtered by bucket to match search constraints)
        db_map_start = time.time()
        faiss_ranked_ids = []
        if faiss_ids:
            cursor = UNIFIED_DB.cursor()
            placeholders = ",".join("?" for _ in faiss_ids)
            bucket_placeholders = ",".join("?" for _ in requested_buckets)
            query = f"""
                SELECT faiss_id, id 
                FROM media 
                WHERE faiss_id IN ({placeholders}) 
                  AND bucket IN ({bucket_placeholders})
                  AND average_score >= ? AND average_score <= ?
                  AND popularity >= ? AND popularity <= ?
            """
            cursor.execute(query, faiss_ids + requested_buckets + [req.min_score, req.max_score, req.min_popularity, req.max_popularity])
            faiss_id_to_db_id = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Build ordered list of db_ids matching FAISS similarity ranking
            for f_id in faiss_ids:
                db_id = faiss_id_to_db_id.get(f_id)
                if db_id is not None:
                    faiss_ranked_ids.append(db_id)
        db_map_time = time.time() - db_map_start

        # 5. Reciprocal Rank Fusion (RRF)
        rrf_start = time.time()
        k = 60
        rrf_scores = {}
        for rank, db_id in enumerate(faiss_ranked_ids, 1):
            rrf_scores[db_id] = rrf_scores.get(db_id, 0.0) + (1.0 / (k + rank))
        for rank, db_id in enumerate(bm25_ranked_ids, 1):
            rrf_scores[db_id] = rrf_scores.get(db_id, 0.0) + (1.0 / (k + rank))
        sorted_rrf = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        top_rrf_candidates = sorted_rrf[:900]
        top_db_ids = [db_id for db_id, score in top_rrf_candidates]
        rrf_score_map = {db_id: score for db_id, score in top_rrf_candidates}
        rrf_time = time.time() - rrf_start
        
    else:
        # No query: fetch top 900 candidates directly based on rating/popularity bounds
        faiss_time = 0.0
        fts_time = 0.0
        db_map_time = 0.0
        rrf_time = 0.0
        
        db_query_start = time.time()
        cursor = UNIFIED_DB.cursor()
        bucket_placeholders = ",".join("?" for _ in requested_buckets)
        query = f"""
            SELECT id, average_score 
            FROM media
            WHERE bucket IN ({bucket_placeholders})
              AND average_score >= ? AND average_score <= ?
              AND popularity >= ? AND popularity <= ?
            ORDER BY average_score DESC, popularity DESC
            LIMIT 900
        """
        cursor.execute(query, requested_buckets + [req.min_score, req.max_score, req.min_popularity, req.max_popularity])
        rows = cursor.fetchall()
        
        top_db_ids = [row[0] for row in rows]
        # Assign a mock RRF score based on the rating so highly rated shows rank first in semantic weight
        rrf_score_map = {row[0]: (row[1] / 100.0 if row[1] else 0.5) for row in rows}
        top_rrf_candidates = [(db_id, score) for db_id, score in rrf_score_map.items()]
        
        # Log DB query time in the FTS slot
        fts_time = time.time() - db_query_start

    # 6. SQLite Metadata fetch (in exactly one batch of 900 candidates)
    db_start = time.time()
    meta = fetch_metadata_by_db_ids(top_db_ids, UNIFIED_DB, "media", requested_buckets)
    db_time = time.time() - db_start

    # 7. Reranking preparation and execution
    rerank_start = time.time()
    reranker_input = []
    
    banned_tags_set = {t.strip().lower() for t in req.banned_tags}
    hard_tags_set = set(req.hard_limit)
    hard_tags_set = {t.strip().lower() for t in hard_tags_set}
    soft_tags_set = set(req.soft_limit + req.demographic + req.genre)
    soft_tags_set = {t.strip().lower() for t in soft_tags_set}

    # Normalize RRF scores to a mock faiss_distance range [0, 1.5]
    if top_rrf_candidates:
        max_rrf = max(score for _, score in top_rrf_candidates)
        min_rrf = min(score for _, score in top_rrf_candidates)
        rrf_range = max_rrf - min_rrf if max_rrf != min_rrf else 1.0
    else:
        max_rrf, min_rrf, rrf_range = 1.0, 0.0, 1.0

    for db_id in top_db_ids:
        row = meta.get(db_id)
        if not row: continue
        
        tags_raw = row[3] or ""
        genres_raw = row[4] or ""
        
        # Translate RRF score into proxy distance [0, 1.5] where higher score -> lower distance
        rrf_score = rrf_score_map[db_id]
        norm_score = (rrf_score - min_rrf) / rrf_range
        mock_dist = 1.5 * (1.0 - norm_score)

        reranker_input.append({
            "title": row[1],
            "description": row[2],
            "tags": parse_tags_genres(tags_raw),
            "genres": parse_tags_genres(genres_raw),
            "average_score": row[5],
            "popularity": row[6],
            "image_url": row[7],
            "bucket": row[8],
            "media_id": int(db_id),
            "faiss_distance": mock_dist
        })

    ranked_results = reranker.ranker(
        candidates=reranker_input, 
        hard_filters=hard_tags_set, 
        soft_filters=soft_tags_set,
        banned_user_filters=banned_tags_set,
        nsfw_allowed=req.nsfw_allowed
    )
    valid_results = [r for r in ranked_results if r.get('rerank_score', -1) >= 0]
    rerank_time = time.time() - rerank_start

    # 8. Relations traversal and deduplication (only resolved for top deduplicated outputs)
    dedup_start = time.time()
    final_output = []
    seen_series = set()
    seen_media_ids = set()
    cache = {}
    
    for item in valid_results:
        media_id = item["media_id"]
        title = item["title"]
        
        # Short-circuit if this specific ID has been resolved in a prior chain
        if media_id in seen_media_ids:
            continue
            
        # Resolve relations chain only for items being evaluated for recommendations
        relations_chain, other_relations, visited_ids = resolve_chain(UNIFIED_DB, media_id, title, cache)
        
        # Determine the series signature (first prequel title if exists, otherwise current title)
        series_signature = relations_chain[0] if relations_chain else title
        series_signature_clean = series_signature.lower().strip()
        
        if series_signature_clean in seen_series:
            # Skip this item as we've already recommended a title from this series chain
            # But track these IDs so we short-circuit future duplicate items of this series
            seen_media_ids.update(visited_ids)
            continue
            
        seen_series.add(series_signature_clean)
        seen_media_ids.update(visited_ids)
        
        final_output.append(RecommendationItem(
            title=title,
            description=item['description'],
            tags=item['tags'],
            genres=item['genres'],
            average_score=item['average_score'],
            popularity=item['popularity'],
            image_url=item.get('image_url'),
            bucket=item.get('bucket'),
            relations_chain=relations_chain,
            other_relations=other_relations
        ))
        
        if len(final_output) >= 20:
            break
            
    dedup_time = time.time() - dedup_start
    total_time = time.time() - start_time
    
    # Output telemetry logs
    print(f"\n--- LATENCY BREAKDOWN (HYBRID SEARCH) ---")
    print(f"Query Embedding:         {query_time*1000:.2f} ms")
    print(f"FAISS Search:            {faiss_time*1000:.2f} ms")
    print(f"BM25 FTS5 Search:        {fts_time*1000:.2f} ms")
    print(f"FAISS Mapping:           {db_map_time*1000:.2f} ms")
    print(f"RRF Merging:             {rrf_time*1000:.2f} ms")
    print(f"SQLite DB Fetch:         {db_time*1000:.2f} ms")
    print(f"Reranker:                {rerank_time*1000:.2f} ms")
    print(f"Relations/Deduplication: {dedup_time*1000:.2f} ms")
    print(f"-----------------------------------------")
    print(f"Total Latency:           {total_time*1000:.2f} ms\n")
    
    return final_output
