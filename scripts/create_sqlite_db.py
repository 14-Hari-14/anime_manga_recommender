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
    
    # Create index on faiss_id for fast queries in the backend API
    print("Creating index on faiss_id...")
    cursor = conn.cursor()
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_faiss_id ON {TABLE_NAME} (faiss_id)")
    conn.commit()
    
    # Verify the table exists and count rows
    cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
    row_count = cursor.fetchone()[0]
    print(f"SUCCESS: Database created at {DB_PATH}. Table '{TABLE_NAME}' has {row_count} rows.")
    
    conn.close()

if __name__ == "__main__":
    main()