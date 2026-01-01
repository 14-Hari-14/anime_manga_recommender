import sqlite3
import requests
import time

# --- CONFIGURATION ---
DB_PATH = "data/anime.db"   # Change to 'data/manga.db' when ready
TABLE_NAME = "anime"        # Change to 'manga' when ready
MEDIA_TYPE = "ANIME"        # Change to 'MANGA' when ready
# ---------------------

def add_column_if_missing(cursor, table):
    """Adds image_url column if it doesn't exist."""
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN image_url TEXT")
        print(f"✅ Added 'image_url' column to {table}.")
    except sqlite3.OperationalError:
        print(f"ℹ️ 'image_url' column already exists in {table}.")

def get_image_url(title, media_type):
    """Queries AniList API for the cover image."""
    query = '''
    query ($search: String, $type: MediaType) {
      Media (search: $search, type: $type) {
        coverImage {
          extraLarge
        }
      }
    }
    '''
    variables = {'search': title, 'type': media_type}
    url = 'https://graphql.anilist.co'

    try:
        response = requests.post(url, json={'query': query, 'variables': variables}, timeout=5)
        if response.status_code == 429:
            print("⚠️ Rate Limit Hit! Sleeping for 60s...")
            time.sleep(60)
            return get_image_url(title, media_type) # Retry
            
        data = response.json()
        if 'errors' in data:
            return None
            
        return data['data']['Media']['coverImage']['extraLarge']
    except Exception as e:
        return None

def hydrate_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Prepare DB
    add_column_if_missing(cursor, TABLE_NAME)
    
    # 2. Find items without images
    print("🔍 Scanning for items missing images...")
    cursor.execute(f"SELECT faiss_id, title FROM {TABLE_NAME} WHERE image_url IS NULL")
    rows = cursor.fetchall()
    
    total = len(rows)
    print(f"found {total} items to update.")
    
    updates = []
    
    # 3. Loop and Fetch
    for i, (faiss_id, title) in enumerate(rows):
        image_link = get_image_url(title, MEDIA_TYPE)
        
        if image_link:
            updates.append((image_link, faiss_id))
            print(f"[{i+1}/{total}] Found: {title[:20]}...")
        else:
            # Mark as 'NA' so we don't query it again next time
            updates.append(("NA", faiss_id)) 
            print(f"[{i+1}/{total}] ❌ No image: {title[:20]}...")

        # 4. Save every 10 items (to be safe)
        if len(updates) >= 10:
            cursor.executemany(f"UPDATE {TABLE_NAME} SET image_url = ? WHERE faiss_id = ?", updates)
            conn.commit()
            updates = []
            
        # 5. Rate Limiting (Crucial)
        # AniList limit: 90 req/min => ~0.66s per request. 
        # We sleep 0.8s to be safe.
        time.sleep(0.8)

    # Final save
    if updates:
        cursor.executemany(f"UPDATE {TABLE_NAME} SET image_url = ? WHERE faiss_id = ?", updates)
        conn.commit()

    conn.close()
    print("🎉 Done!")

if __name__ == "__main__":
    hydrate_db()