import requests
import csv
import time
import os

ANILIST_URL = "https://graphql.anilist.co"
OUTPUT_FILE = "anime.csv"
PROGRESS_FILE = "anime_progress.txt"

QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo {
      hasNextPage
      currentPage
    }
    media(type: ANIME) {
      id
      title {
        romaji
        english
      }
      description
      genres
      tags {
        name
        rank
      }
      coverImage {
        extraLarge
      }
      averageScore
      popularity
      startDate {
        year
      }
    }
  }
}
"""

def load_last_page():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            return int(f.read().strip())
    return 1

def save_progress(page):
    with open(PROGRESS_FILE, "w") as f:
        f.write(str(page))


def fetch_all_anime(per_page=50, sleep_time=2.2):
    page = load_last_page()
    file_exists = os.path.exists(OUTPUT_FILE)

    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Write header only once
        if not file_exists:
            writer.writerow([
                "id",
                "title",
                "description",
                "genres",
                "tags",
                "year",
                "average_score",
                "popularity",
                "image_url"
            ])

        while True:
            variables = {
                "page": page,
                "perPage": per_page
            }

            response = requests.post(
                ANILIST_URL,
                json={"query": QUERY, "variables": variables}
            )

            if response.status_code != 200:
                print(f"Request failed at page {page}")
                break

            data = response.json()
            page_data = data["data"]["Page"]
            media = page_data["media"]

            if not media:
                print("No more data returned.")
                break

            for anime in media:
                    # Handle potential missing titles safely
                    title = anime["title"]["english"] or anime["title"]["romaji"] or "Unknown Title"
                    
                    # Handle missing image safely
                    image_url = "NA"
                    if anime.get("coverImage") and anime["coverImage"].get("extraLarge"):
                        image_url = anime["coverImage"]["extraLarge"]
                        
                    # Write the row with all required fields
                    writer.writerow([
                        anime["id"],
                        title,
                        image_url,
                        anime["description"] or "", # Handle None desc
                        ",".join(anime["genres"] or []),
                        ",".join([t["name"] for t in (anime["tags"] or [])]),
                        anime["startDate"]["year"] if anime["startDate"] else "",
                        anime["averageScore"] or 0,
                        anime["popularity"] or 0
                    ])
            print(f"Fetched page {page}")

            save_progress(page)

            if not page_data["pageInfo"]["hasNextPage"]:
                print("Reached final page.")
                break

            page += 1
            time.sleep(sleep_time)  # RATE LIMIT

fetch_all_anime()
print("Anime ingestion complete.")
