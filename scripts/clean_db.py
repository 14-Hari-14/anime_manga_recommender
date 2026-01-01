import sqlite3
import time

# the script to clean the database entries for tags and genres fields
def fast_clean(db_path, table_name):
    print(f"\n--- OPTIMIZING & CLEANING: {db_path} ---")
    start_time = time.time()
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Create Index for Speed (Crucial for large DBs)
    print("1. Creating index...")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_faiss_id ON {table_name} (faiss_id)")
    conn.commit()

    # 2. Read Data
    print("2. Reading data...")
    cursor.execute(f"SELECT faiss_id, tags, genres FROM {table_name}")
    rows = cursor.fetchall()
    
    updates = []
    
    # 3. Process in Memory
    for row in rows:
        faiss_id, raw_tags, raw_genres = row
        
        def clean_field(text):
            if not text: return ""
            # Only process if it looks dirty (has brackets)
            if "[" in text or "]" in text:
                return text.replace("[", "").replace("]", "").replace("'", "").replace('"', "")
            return text

        new_tags = clean_field(raw_tags)
        new_genres = clean_field(raw_genres)
        
        if new_tags != raw_tags or new_genres != raw_genres:
            updates.append((new_tags, new_genres, faiss_id))

    # 4. Bulk Update
    if updates:
        print(f"3. Cleaning {len(updates)} dirty rows...")
        try:
            cursor.execute("BEGIN TRANSACTION")
            cursor.executemany(
                f"UPDATE {table_name} SET tags = ?, genres = ? WHERE faiss_id = ?", 
                updates
            )
            cursor.execute("COMMIT")
        except Exception as e:
            print(f"   Error: {e}")
            cursor.execute("ROLLBACK")
    else:
        print("3. No updates needed (Data might already be clean).")
    
    conn.close()
    print(f"   Done in {round(time.time() - start_time, 2)}s")

def verify_clean(db_path, table_name):
    """Checks if any brackets remain in the database."""
    print(f"--- VERIFYING: {db_path} ---")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Query for any rows that still contain brackets
    query = f"""
        SELECT count(*) FROM {table_name} 
        WHERE tags LIKE '%[%' 
           OR tags LIKE '%]%' 
           OR genres LIKE '%[%' 
           OR genres LIKE '%]%'
    """
    cursor.execute(query)
    count = cursor.fetchone()[0]
    
    if count == 0:
        print(f"SUCCESS: {table_name} table is 100% CLEAN.")
    else:
        print(f"FAILURE: Found {count} rows that are still dirty.")
        
        # Show a sample of what failed
        print("   Sample of dirty data:")
        cursor.execute(f"SELECT title, tags, genres FROM {table_name} WHERE tags LIKE '%[%' LIMIT 3")
        for row in cursor.fetchall():
            print(f"   - {row[0]}: {row[1]}")

    conn.close()

if __name__ == "__main__":
    # 1. Clean and Verify Anime
    fast_clean("data/anime.db", "anime")
    verify_clean("data/anime.db", "anime")
    
    # 2. Clean and Verify Manga
    fast_clean("data/manga.db", "manga")
    verify_clean("data/manga.db", "manga")