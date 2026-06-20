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

from reranking_results import ReRanker
reranker = ReRanker()
# TODO
# 1. Remove cache complexity the benefit is rather small


# Request Schema (format for data to be recieved)
class RecommendationRequest(BaseModel):
    query: str = Field(..., description="Natural language query")
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
    
    # 1. Embed query
    query_start = time.time()
    query_vec = embed_query(req.query)
    query_time = time.time() - query_start
    
    requested_buckets = list(set(req.content_type))
    if not requested_buckets:
        return []

    # 2. FAISS deep search
    faiss_start = time.time()
    SEARCH_DEPTH = 900 # get top 900 from the unified index
    D, I = UNIFIED_INDEX.search(query_vec, k=SEARCH_DEPTH)
    faiss_time = time.time() - faiss_start

    # 3. SQLite Metadata fetch
    db_start = time.time()
    faiss_ids = [int(idx) for idx in I[0] if idx >= 0]
    meta = fetch_metadata(faiss_ids, UNIFIED_DB, "media", requested_buckets)
    db_time = time.time() - db_start

    # 4. Reranking preparation and execution
    rerank_start = time.time()
    reranker_input = []
    
    banned_tags_set = {t.strip().lower() for t in req.banned_tags}
    hard_tags_set = set(req.hard_limit + req.genre)
    hard_tags_set = {t.strip().lower() for t in hard_tags_set}
    soft_tags_set = set(req.soft_limit + req.demographic)
    soft_tags_set = {t.strip().lower() for t in soft_tags_set}

    for dist, faiss_id in zip(D[0], I[0]):
        if faiss_id < 0: continue
        row = meta.get(int(faiss_id))
        if not row: continue
        
        tags_raw = row[3] or ""
        genres_raw = row[4] or ""
        media_id = row[10]

        reranker_input.append({
            "title": row[1],
            "description": row[2],
            "tags": parse_tags_genres(tags_raw),
            "genres": parse_tags_genres(genres_raw),
            "average_score": row[5],
            "popularity": row[6],
            "image_url": row[7],
            "bucket": row[8],
            "media_id": int(media_id),
            "faiss_distance": dist
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

    # SRelations traversal and deduplication (only resolved for top deduplicated outputs)
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
    print(f"\n--- LATENCY BREAKDOWN ---")
    print(f"Query Embedding:     {query_time*1000:.2f} ms")
    print(f"FAISS Search:        {faiss_time*1000:.2f} ms")
    print(f"SQLite DB Fetch:     {db_time*1000:.2f} ms")
    print(f"Reranker:            {rerank_time*1000:.2f} ms")
    print(f"Relations/Deduplication: {dedup_time*1000:.2f} ms")
    print(f"-------------------------")
    print(f"Total Latency:       {total_time*1000:.2f} ms\n")
    
    return final_output
