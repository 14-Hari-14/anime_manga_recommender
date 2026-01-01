import faiss
import sqlite3
from sentence_transformers import SentenceTransformer
import random

anime_query_list = [
    "dark fantasy anime with demons and magic",
    "office romance anime with comedy and wholesome moments",
    "I don’t know what to watch, give me something interesting"
]

manga_query_list = [
    "historical manga set in ancient China or Japan",
    "cute and relaxing slice of life manga",
    "the best martial arts manga"
]
query = random.choice(manga_query_list)

anime_index_path = "data/vector_stores/anime_index.faiss"

manga_index_path = "data/vector_stores/manga_index.faiss"

loaded_index = faiss.read_index(manga_index_path) # change to anime_index_path for anime search
# print(f"Index successfully loaded from {index_path}. Total vectors: {loaded_index.ntotal}")

embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
embedded_query = embedding_model.encode(query, show_progress_bar = True)
print(query, embedded_query.shape)

xq = embedded_query.reshape(1, -1) # -1 tells to calculate the correct size of the array
print("Reshaped query shape:", xq.shape)

k = 5

D, I = loaded_index.search(xq.astype('float32'), k)

top_k_indices = I[0].tolist()

valid_indices = [str(idx) for idx in top_k_indices if idx >= 0]

conn = sqlite3.connect("data/manga.db") # here as well, change to anime.db for anime search
curr = conn.cursor()

if not valid_indices:
    print("No valid output")
else:
    indices_string = ", ".join(valid_indices)
    sql_anime_query = f"SELECT faiss_id, title, description_clean, tags, average_score FROM anime WHERE faiss_id IN ({indices_string})"
    
    sql_manga_query = f"SELECT faiss_id, title, description_clean, tags, average_score FROM manga WHERE faiss_id IN ({indices_string})"
    curr.execute(sql_manga_query)

    recommendations = curr.fetchall()

    conn.close()
    
    content_map = {row[0]: row for row in recommendations}

    print("\n--- Top 5 Recommendations ---")
    
    
    for rank, item_id in enumerate(top_k_indices):
        if item_id in content_map:
            # Retrieve the specific row tuple from the map
            row = content_map[item_id]
            
            # Unpack the fields based on the SELECT statement order:
            # id (0), title (1), description (2), tags (3), average_score(4)
            title = row[1]
            description_clean = row[2]
            tags = row[3]
            average_score = row[4]
            
            print(f"Rank {rank + 1} (ID: {item_id}):")
            print(f"Title: {title}")
            print(f"Rating: {average_score}")
            print(f"Tags: {tags}")
            print(f"Description: {description_clean}\n")