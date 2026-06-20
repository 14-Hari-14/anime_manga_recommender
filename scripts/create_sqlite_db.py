import pandas as pd
import sqlite3
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Define paths relative to the project root directory
CSV_PATH = BASE_DIR.parent / "data" / "cleaned_collections_with_combined_text.csv"
DB_PATH = BASE_DIR.parent / "data" / "recommendations.db"
TABLE_NAME = "media"

def main():
    print(f"Loading cleaned dataset from {CSV_PATH}...")
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError(f"Source CSV file not found at {CSV_PATH}. Please run the embeddings script first.")
        
    df = pd.read_csv(CSV_PATH, low_memory=False)
    
    # Ensure faiss_id aligns perfectly with row indices
    df = df.reset_index(drop=True)
    if "faiss_id" not in df.columns:
        df.insert(0, "faiss_id", df.index)
    else:
        df["faiss_id"] = df.index
        
    print(f"Loaded {len(df)} rows. Inserting into SQLite database...")
    
    # Ensure the parent directory for the database exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    # Connect and save
    conn = sqlite3.connect(DB_PATH)
    
    df.to_sql(
        name=TABLE_NAME,
        con=conn,
        if_exists="replace",
        index=False
    )
    
    # Create indices for fast queries in the backend API
    print("Creating indices on faiss_id and id...")
    cursor = conn.cursor()
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_faiss_id ON {TABLE_NAME} (faiss_id)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_id ON {TABLE_NAME} (id)")
    conn.commit()
    
    # Create and populate FTS5 virtual table
    print("Creating and populating FTS5 virtual table 'media_fts' for BM25...")
    cursor.execute("DROP TABLE IF EXISTS media_fts")
    cursor.execute("""
        CREATE VIRTUAL TABLE media_fts USING fts5(
            id UNINDEXED,
            title,
            description,
            genres,
            tags,
            combined_text
        )
    """)
    cursor.execute("""
        INSERT INTO media_fts(id, title, description, genres, tags, combined_text)
        SELECT id, title, description, genres, tags, combined_text FROM media
    """)
    conn.commit()
    
    # Verify the table exists and count rows
    cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
    row_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM media_fts")
    fts_count = cursor.fetchone()[0]
    print(f"SUCCESS: Database created at {DB_PATH}.")
    print(f"Table '{TABLE_NAME}' has {row_count} rows.")
    print(f"Virtual FTS5 table 'media_fts' has {fts_count} rows.")
    
    conn.close()

if __name__ == "__main__":
    main()