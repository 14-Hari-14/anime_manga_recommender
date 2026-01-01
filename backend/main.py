from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Literal
import faiss
import sqlite3
import numpy as np
from sentence_transformers import SentenceTransformer
import os

from reranking_results import ReRanker
reranker = ReRanker()


# Request Schema (format for data to be recieved)
class RecommendationRequest(BaseModel):
    query: str = Field(..., description="Natural language query")
    content_type: List[Literal["Anime", "Manga"]]

    format: List[str] = []
    
    # Overall themes is removed. only use hard tags to enforce must have tags, soft tags to boost scores for prefered tags and banned tags to exclude items with these tags
    hard_limit: List[str] = [] 
    soft_limit: List[str] = []
    banned_tags: List[str] = []
    
    # These are still passed from frontend, so we keep them in schema
    genre: List[str] = []
    viewer_descretion: List[str] = []
    demographic: List[str] = []

# Response schema (format for data to be sent back)
class RecommendationItem(BaseModel):
    title: str
    description: str
    tags: List[str]
    genres: List[str]
    average_score: float | None
    popularity: int | None
    image_url: str | None



# Initializing the app as well as the index and db
app = FastAPI(title="Anime / Manga Recommendation API")
EMBEDDING_MODEL = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
ANIME_INDEX = faiss.read_index("../data/vector_stores/anime_index.faiss")
MANGA_INDEX = faiss.read_index("../data/vector_stores/manga_index.faiss")
ANIME_DB = sqlite3.connect("../data/anime.db", check_same_thread=False)
MANGA_DB = sqlite3.connect("../data/manga.db", check_same_thread=False)

# check to see if the connections were successful
print("--- DATA HEALTH CHECK ---")
print(f"Anime Index Size: {ANIME_INDEX.ntotal} vectors")
print(f"Manga Index Size: {MANGA_INDEX.ntotal} vectors")
print("-------------------------")

# Embed the user query in a faiss index compatible format float32
def embed_query(text: str) -> np.ndarray:
    vec = EMBEDDING_MODEL.encode(text)
    vec = vec.astype("float32")
    vec /= np.linalg.norm(vec) + 1e-12
    return vec.reshape(1, -1)

# Fetch the actual name and details from the database corresponding to the faiss index
def fetch_metadata(ids: List[int], conn: sqlite3.Connection, table: str):
    results = {}
    BATCH_SIZE = 900 # sending 900 ids at a time
    cursor = conn.cursor()

    for i in range(0, len(ids), BATCH_SIZE):
        batch_ids = ids[i : i + BATCH_SIZE]
        if not batch_ids: continue
        
        placeholders = ",".join("?" for _ in batch_ids)
        
        # gets the data we want to display on frontend from the db
        query = f"""
            SELECT faiss_id, title, description_clean, tags, genres, average_score, popularity, image_url
            FROM {table}
            WHERE faiss_id IN ({placeholders})
        """
        
        cursor.execute(query, batch_ids)
        rows = cursor.fetchall()
        for row in rows:
            results[row[0]] = row
    return results


# Recommendation Endpoint
@app.post("/recommend", response_model=List[RecommendationItem])
def recommend(req: RecommendationRequest):
    query_vec = embed_query(req.query)
    
    # -- 1. DEEP SEARCH --
    all_candidates = []
    SEARCH_DEPTH = 2000 # get top 2000 from the required index

    if "Anime" in req.content_type:
        # d = distance required to calculate similarity between user promt and description of anime / manga
        # i = index of the anime / manga in the faiss index to fetch metadata later
        D, I = ANIME_INDEX.search(query_vec, k=SEARCH_DEPTH)
        for dist, idx in zip(D[0], I[0]):
            if idx >= 0: all_candidates.append((dist, int(idx), "Anime"))

    if "Manga" in req.content_type:
        D, I = MANGA_INDEX.search(query_vec, k=SEARCH_DEPTH)
        for dist, idx in zip(D[0], I[0]):
            if idx >= 0: all_candidates.append((dist, int(idx), "Manga"))

    # getting id from candidates and storing in respective lists
    anime_ids = [c[1] for c in all_candidates if c[2] == "Anime"]
    manga_ids = [c[1] for c in all_candidates if c[2] == "Manga"]
    
    # fetched data from the db
    anime_meta = fetch_metadata(anime_ids, ANIME_DB, "anime") if anime_ids else {}
    manga_meta = fetch_metadata(manga_ids, MANGA_DB, "manga") if manga_ids else {}

    # preparing data to be sent to reranker
    reranker_input = []
    # hard tags are must have, ids without these will be filtered out
    hard_tags_set = {t.strip().lower() for t in req.hard_limit}
    # banned tags are must not have sets, ids with these will be filtered out
    banned_tags_set = {t.strip().lower() for t in req.banned_tags}

    # combine soft tags with genres and demographic tags, ids without these will get penalized but not filtered out
    soft_tags_set = set(req.soft_limit + req.genre + req.demographic)
    soft_tags_set = {t.strip().lower() for t in soft_tags_set}
    
    

    for dist, faiss_id, c_type in all_candidates:
        row = anime_meta.get(faiss_id) if c_type == "Anime" else manga_meta.get(faiss_id)
        if not row: continue
        
        # the data structure expected by the reranker
        reranker_input.append({
            "title": row[1],
            "description": row[2],
            "tags": row[3].split(","),
            "genres": row[4].split(","),
            "average_score": row[5],
            "popularity": row[6],
            "image_url": row[7],
            "faiss_distance": dist
        })

    # getting the reranked results (still contains 2000 items but ordered by relevance now)
    ranked_results = reranker.ranker(
        candidates=reranker_input, 
        hard_filters=hard_tags_set, 
        soft_filters=soft_tags_set,
        banned_filters=banned_tags_set
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
            popularity = item['popularity'],
            image_url = item.get('image_url')
        ))
        
    return final_output