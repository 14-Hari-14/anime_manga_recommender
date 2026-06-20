import sqlite3
import random
import time
import re
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

# Load embedding model
print("Loading model sentence-transformers/all-MiniLM-L6-v2...")
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

# Connect to database
DB_PATH = "data/recommendations.db"
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

def clean_html(text):
    if not text:
        return ""
    # remove tags
    clean = re.compile('<.*?>')
    text = re.sub(clean, '', text)
    # remove ANN source text
    text = re.sub(r'\(Source:.*?\)', '', text)
    return text.strip()

# 1. Fetch 6 random real titles and 6 random synthetic titles
print("Selecting 6 real and 6 synthetic titles...")
cursor.execute("""
    SELECT id, title, description, genres, tags, combined_text, bucket, status, description_is_synthetic
    FROM media
    WHERE description_is_synthetic = 0 AND description IS NOT NULL AND length(description) > 50
    ORDER BY random() LIMIT 6
""")
real_rows = cursor.fetchall()

cursor.execute("""
    SELECT id, title, description, genres, tags, combined_text, bucket, status, description_is_synthetic
    FROM media
    WHERE description_is_synthetic = 1 AND description IS NOT NULL
    ORDER BY random() LIMIT 6
""")
synthetic_rows = cursor.fetchall()

target_rows = real_rows + synthetic_rows

# 2. Fetch 1000 random distractor titles
print("Selecting 1000 distractor titles...")
cursor.execute("""
    SELECT id, title, description, genres, tags, combined_text, bucket, status, description_is_synthetic
    FROM media
    WHERE id NOT IN ({})
    ORDER BY random() LIMIT 1000
""".format(", ".join(str(r[0]) for r in target_rows)))
distractor_rows = cursor.fetchall()

conn.close()

# Combine targets and distractors
all_rows = target_rows + distractor_rows

# Helper to format genres/tags lists
def clean_tags(raw_str):
    if not raw_str or pd.isna(raw_str): return []
    cleaned = raw_str.replace("[", "").replace("]", "").replace("'", "").replace('"', "")
    return [t.strip() for t in cleaned.split(",") if t.strip()]

# Prepare queries for each target title
print("\nGenerating queries for target titles...")
test_cases = []
for row in target_rows:
    media_id, title, desc, genres_raw, tags_raw, combined_text, bucket, status, is_synth = row
    
    genres = clean_tags(genres_raw)
    tags = clean_tags(tags_raw)
    clean_desc = clean_html(desc)
    
    queries = {}
    
    # Query 1: Plot/Keyword Search
    if is_synth == 0:
        # For real description: extract a key sentence or a chunk of 8-12 words
        sentences = [s.strip() for s in clean_desc.split(".") if len(s.strip().split()) >= 6]
        if sentences:
            queries["Plot Query"] = sentences[0]
        else:
            words = clean_desc.split()
            queries["Plot Query"] = " ".join(words[:10])
    else:
        # For synthetic: build a specific search query based on format & themes
        g_part = genres[0] if genres else "drama"
        t_part = f"with {tags[0]} themes" if tags else ""
        queries["Plot Query"] = f"A {bucket} containing {g_part} elements {t_part}".strip()
        
    # Query 2: Thematic / Conceptual Search
    if genres and tags:
        queries["Thematic Query"] = f"a {bucket} about {genres[0]} and {genres[-1]} featuring {tags[0]}"
    elif genres:
        queries["Thematic Query"] = f"a {bucket} with genres like {genres[0]}"
    else:
        queries["Thematic Query"] = f"a {bucket} with interesting themes"
        
    # Query 3: Title Similarity Search
    queries["Title Query"] = f"something like the title {title}"
    
    test_cases.append({
        "id": media_id,
        "title": title,
        "is_synthetic": is_synth,
        "description": clean_desc,
        "combined_text": combined_text,
        "queries": queries
    })

# Compute pool embeddings
print("\nComputing embeddings for pool of 1012 items...")
descriptions_pool = [clean_html(r[2]) for r in all_rows]
combined_pool = [r[5] for r in all_rows]

t0 = time.time()
desc_embeddings = model.encode(descriptions_pool, show_progress_bar=True, convert_to_numpy=True)
desc_embeddings = desc_embeddings / np.linalg.norm(desc_embeddings, axis=1, keepdims=True)

comb_embeddings = model.encode(combined_pool, show_progress_bar=True, convert_to_numpy=True)
comb_embeddings = comb_embeddings / np.linalg.norm(comb_embeddings, axis=1, keepdims=True)
print(f"Computed embeddings in {time.time() - t0:.2f} seconds.")

# Rank comparison
results = []

for idx, case in enumerate(test_cases):
    target_idx = idx # since target_rows are placed first in all_rows
    
    case_results = {
        "title": case["title"],
        "is_synthetic": "Synthetic" if case["is_synthetic"] else "Real",
        "queries": []
    }
    
    for q_type, q_text in case["queries"].items():
        # Embed query
        q_vec = model.encode(q_text)
        q_vec = q_vec / np.linalg.norm(q_vec)
        
        # Calculate similarities in Description Pool
        desc_sims = np.dot(desc_embeddings, q_vec)
        # Rank: count how many are strictly greater + 1
        desc_rank = np.sum(desc_sims > desc_sims[target_idx]) + 1
        
        # Calculate similarities in Combined Text Pool
        comb_sims = np.dot(comb_embeddings, q_vec)
        comb_rank = np.sum(comb_sims > comb_sims[target_idx]) + 1
        
        case_results["queries"].append({
            "type": q_type,
            "query": q_text,
            "desc_rank": int(desc_rank),
            "comb_rank": int(comb_rank)
        })
        
    results.append(case_results)

# Print Detailed Results
print("\n" + "="*90)
print(f"{'TITLE (TYPE)':<40} | {'QUERY TYPE':<15} | {'DESC RANK':<9} | {'COMB RANK':<9} | {'WINNER'}")
print("="*90)

desc_ranks_real, comb_ranks_real = [], []
desc_ranks_synth, comb_ranks_synth = [], []

for res in results:
    title_label = f"{res['title'][:28]} ({res['is_synthetic']})"
    for q in res["queries"]:
        winner = "COMBINED" if q["comb_rank"] < q["desc_rank"] else ("DESCRIPTION" if q["desc_rank"] < q["comb_rank"] else "TIE")
        print(f"{title_label:<40} | {q['type']:<15} | {q['desc_rank']:<9d} | {q['comb_rank']:<9d} | {winner}")
        
        # Collect for averages
        if res["is_synthetic"] == "Real":
            desc_ranks_real.append(q["desc_rank"])
            comb_ranks_real.append(q["comb_rank"])
        else:
            desc_ranks_synth.append(q["desc_rank"])
            comb_ranks_synth.append(q["comb_rank"])

print("="*90)

# Print Summary Averages
print("\nSUMMARY STATS (AVERAGE RANK - Lower is Better):")
print(f"Real Descriptions (6 titles, 18 queries):")
print(f"  - Description-Only Embedding Avg Rank: {np.mean(desc_ranks_real):.1f}")
print(f"  - Combined-Text Embedding Avg Rank:      {np.mean(comb_ranks_real):.1f}")
print(f"Synthetic Descriptions (6 titles, 18 queries):")
print(f"  - Description-Only Embedding Avg Rank: {np.mean(desc_ranks_synth):.1f}")
print(f"  - Combined-Text Embedding Avg Rank:      {np.mean(comb_ranks_synth):.1f}")

print("\nOverall Average:")
print(f"  - Description-Only Embedding Avg Rank: {np.mean(desc_ranks_real + desc_ranks_synth):.1f}")
print(f"  - Combined-Text Embedding Avg Rank:      {np.mean(comb_ranks_real + comb_ranks_synth):.1f}")
print("="*90)