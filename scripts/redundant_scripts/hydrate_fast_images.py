import sqlite3
import requests
import time

# --- CONFIGURATION ---
# UPDATE THESE FOR MANGA LATER
DB_PATH = "data/anime.db" 
TABLE_NAME = "anime"      
MEDIA_TYPE = "ANIME"      
# ---------------------

ANILIST_URL = "https://graphql.anilist.co"

QUERY = """
query ($page: Int, $perPage: Int, $type: MediaType) {
  Page(page: $page, perPage: $perPage) {
    pageInfo {
      hasNextPage
      currentPage
    }
    media(type: $type) {
      title {
        romaji
        english
      }
      coverImage {
        extraLarge
      }
    }
  }
}
"""

def add_column_if_missing(cursor, table):
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN image_url TEXT")
    except sqlite3.OperationalError:
        pass

def load_local_db_map(cursor, table):
    """
    Reads all titles from your DB into memory for instant matching.
    Returns a dict: { "Naruto": [id1], "Bleach": [id2] }
    """
    print("Loading local database into memory map...")
    cursor.execute(f"SELECT faiss_id, title FROM {table} WHERE image_url IS NULL")
    rows = cursor.fetchall()
    
    title_map = {}
    count = 0
    for faiss_id, title in rows:
        clean_title = title.strip().lower()
        if clean_title not in title_map:
            title_map[clean_title] = []
        title_map[clean_title].append(faiss_id)
        count += 1
    
    print(f"Loaded {count} items waiting for images.")
    return title_map

def fast_hydrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    add_column_if_missing(cursor, TABLE_NAME)
    
    # 1. Create a map of your current data: { "title": [faiss_ids...] }
    # This lets us match data without querying the DB 50 times
    title_map = load_local_db_map(cursor, TABLE_NAME)
    
    if not title_map:
        print("🎉 No items need images! You are done.")
        return

    page = 1
    matches_found = 0
    
    print(f"--- STARTING BULK STREAM FOR {MEDIA_TYPE} ---")

    while True:
        try:
            # 2. Fetch 50 items at once from AniList
            variables = {
                "page": page,
                "perPage": 50,
                "type": MEDIA_TYPE
            }
            
            response = requests.post(ANILIST_URL, json={"query": QUERY, "variables": variables})
            
            # Rate Limit Handling
            if response.status_code == 429:
                print("⚠️ Rate Limit! Sleeping 60s...")
                time.sleep(60)
                continue
                
            data = response.json()
            if "errors" in data:
                print("Error:", data["errors"])
                break
                
            page_data = data["data"]["Page"]
            media_list = page_data["media"]
            
            # 3. Process the batch
            batch_updates = []
            
            for item in media_list:
                # Try English title first, then Romaji (matching your old script logic)
                t_eng = item["title"]["english"]
                t_rom = item["title"]["romaji"]
                img_url = item["coverImage"]["extraLarge"]
                
                # Check if we have this title in our DB (English)
                if t_eng:
                    key = t_eng.strip().lower()
                    if key in title_map:
                        for fid in title_map[key]:
                            batch_updates.append((img_url, fid))
                        # Remove from map so we don't update it again
                        del title_map[key]
                
                # Check Romaji if English didn't match
                if t_rom:
                    key = t_rom.strip().lower()
                    if key in title_map:
                        for fid in title_map[key]:
                            batch_updates.append((img_url, fid))
                        del title_map[key]

            # 4. Save to DB
            if batch_updates:
                cursor.executemany(f"UPDATE {TABLE_NAME} SET image_url = ? WHERE faiss_id = ?", batch_updates)
                conn.commit()
                matches_found += len(batch_updates)
                print(f"Page {page}: Updated {len(batch_updates)} items. (Total: {matches_found})")
            else:
                print(f"Page {page}: No matches found locally.")

            # 5. Check strictly for end
            if not page_data["pageInfo"]["hasNextPage"]:
                print("Reached end of AniList.")
                break
            
            page += 1
            # Sleep slightly to be nice (approx 30 pages/min = 1500 items/min)
            time.sleep(1.5) 
            
        except Exception as e:
            print(f"Crash at page {page}: {e}")
            time.sleep(5)

    conn.close()
    print("--- Done! Run the slow script to catch stragglers. ---")

if __name__ == "__main__":
    fast_hydrate()