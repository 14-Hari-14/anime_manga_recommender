from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Literal
import faiss
import sqlite3
import numpy as np
from sentence_transformers import SentenceTransformer
import os
import json

from reranking_results import ReRanker
reranker = ReRanker()


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
    BATCH_SIZE = 900 # sending 900 ids at a time
    cursor = conn.cursor()

    bucket_placeholders = ",".join("?" for _ in buckets)

    for i in range(0, len(ids), BATCH_SIZE):
        batch_ids = ids[i : i + BATCH_SIZE]
        if not batch_ids: continue
        
        placeholders = ",".join("?" for _ in batch_ids)
        
        # gets the data we want to display on frontend from the db
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

def resolve_chain(conn: sqlite3.Connection, start_id: int, start_title: str) -> tuple[List[str], List[str]]:
    visited = {start_id}
    
    # 1. Traverse prequels (backward)
    prequels = []
    curr_id = start_id
    curr_relations_str, _ = get_relations_by_id(conn, curr_id)
    
    for _ in range(10): # limit depth to prevent infinite loops
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
            curr_relations_str, _ = get_relations_by_id(conn, curr_id)
        else:
            break
            
    # Reverse prequels to go from oldest to newest
    prequels.reverse()
    
    # 2. Traverse sequels (forward)
    sequels = []
    curr_id = start_id
    curr_relations_str, _ = get_relations_by_id(conn, curr_id)
    
    for _ in range(10): # limit depth
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
            curr_relations_str, _ = get_relations_by_id(conn, curr_id)
        else:
            break
            
    # 3. Extract other relations from the recommended item's relations string
    other_relations = []
    curr_relations_str, _ = get_relations_by_id(conn, start_id)
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

    return relations_chain, other_relations


# Recommendation Endpoint
@app.post("/recommend", response_model=List[RecommendationItem])
def recommend(req: RecommendationRequest):
    query_vec = embed_query(req.query)
    
    # Map request content types directly to database buckets without any backward compatibility mapping
    requested_buckets = list(set(req.content_type))

    if not requested_buckets:
        return []

    # -- 1. DEEP SEARCH --
    SEARCH_DEPTH = 2000 # get top 2000 from the unified index
    D, I = UNIFIED_INDEX.search(query_vec, k=SEARCH_DEPTH)

    faiss_ids = [int(idx) for idx in I[0] if idx >= 0]
    
    # Fetch metadata from SQLite database, filtering by the requested buckets
    meta = fetch_metadata(faiss_ids, UNIFIED_DB, "media", requested_buckets)

    # preparing data to be sent to reranker
    reranker_input = []
    
    # banned tags are must not have sets, ids with these will be filtered out
    banned_tags_set = {t.strip().lower() for t in req.banned_tags}
    
    # hard tags are must have, ids without these will be filtered out
    hard_tags_set = set(req.hard_limit + req.genre)
    hard_tags_set = {t.strip().lower() for t in hard_tags_set}
    
    # combine soft tags with genres and demographic tags, ids without these will get penalized but not filtered out
    soft_tags_set = set(req.soft_limit + req.demographic)
    soft_tags_set = {t.strip().lower() for t in soft_tags_set}

    for dist, faiss_id in zip(D[0], I[0]):
        if faiss_id < 0: continue
        row = meta.get(int(faiss_id))
        if not row: continue
        
        tags_raw = row[3] or ""
        genres_raw = row[4] or ""
        media_id = row[10]

        # Resolve full prequel/sequel relations chain
        relations_chain, other_relations = resolve_chain(UNIFIED_DB, int(media_id), row[1])

        reranker_input.append({
            "title": row[1],
            "description": row[2],
            "tags": [t.strip() for t in tags_raw.split(",") if t.strip()] if isinstance(tags_raw, str) else [],
            "genres": [g.strip() for g in genres_raw.split(",") if g.strip()] if isinstance(genres_raw, str) else [],
            "average_score": row[5],
            "popularity": row[6],
            "image_url": row[7],
            "bucket": row[8],
            "relations_chain": relations_chain,
            "other_relations": other_relations,
            "faiss_distance": dist
        })

    # getting the reranked results (still contains 2000 items but ordered by relevance now)
    ranked_results = reranker.ranker(
        candidates=reranker_input, 
        hard_filters=hard_tags_set, 
        soft_filters=soft_tags_set,
        banned_user_filters=banned_tags_set,
        nsfw_allowed=req.nsfw_allowed
    )
    
    # filtering out scores with -1 since they are disqualified by hard filters
    valid_results = [r for r in ranked_results if r.get('rerank_score', -1) >= 0]
    
    # preparing the final output to be sent to the frontend for display
    final_output = []
    for item in valid_results[:20]:
        final_output.append(RecommendationItem(
            title=item['title'],
            description=item['description'],
            tags=item['tags'],
            genres=item['genres'],
            average_score=item['average_score'],
            popularity=item['popularity'],
            image_url=item.get('image_url'),
            bucket=item.get('bucket'),
            relations_chain=item.get('relations_chain', []),
            other_relations=item.get('other_relations', [])
        ))
        
    return final_output
