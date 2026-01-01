import pandas as pd
import numpy as np
import sqlite3

df_anime = pd.read_csv("data/cleaned_anime_collections_with_combined_text.csv")
df_manga = pd.read_csv("data/cleaned_manga_collections_with_combined_text.csv")

df_anime = df_anime.reset_index(drop=True)
df_anime.insert(0, "faiss_id", df_anime.index)

df_manga = df_manga.reset_index(drop=True)
df_manga.insert(0, "faiss_id", df_manga.index)

conn = sqlite3.connect("anime.db")

df_anime.to_sql(
    name="anime",
    con=conn,
    if_exists="replace",
    index=False
)

conn.close()

conn = sqlite3.connect("manga.db")

df_manga.to_sql(
    name="manga",
    con=conn,
    if_exists="replace",
    index=False
)

conn.close()