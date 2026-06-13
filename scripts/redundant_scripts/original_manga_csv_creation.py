# creating a graphql query to get anime and manga data from anilist. This will be the first version of the database and will be updated intermittently
import requests
import csv
import time
import pandas as pd
import numpy as np

ANILIST_URL = "https://graphql.anilist.co"

QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(type: MANGA, sort: POPULARITY_DESC) {
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
      averageScore
      popularity
      startDate {
        year
      }
    }
  }
}
"""
# function to create query and get the results
def fetch_manga(max_pages=5, per_page=50):
    all_manga = []

    # loop through pages to get all manga
    for page in range(1, max_pages + 1):
        variables = {
            "page": page,
            "perPage": per_page
        }

        # create the query 
        response = requests.post(
            ANILIST_URL,
            json={"query": QUERY, "variables": variables}
        )

        # store the results 
        data = response.json()

        media = data["data"]["Page"]["media"]
        if not media:
            break

        all_manga.extend(media)
        time.sleep(1)  

    return all_manga

def save_to_csv(manga_list, filename="manga.csv"):
    try: 
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            writer.writerow([
                "id",
                "title",
                "description",
                "genres",
                "tags",
                "year",
                "average_score",
                "popularity"
            ])

            for manga in manga_list:
                writer.writerow([
                    manga["id"],
                    manga["title"]["english"] or manga["title"]["romaji"],
                    manga["description"],
                    ",".join(manga["genres"]),
                    ",".join([t["name"] for t in manga["tags"]]),
                    manga["startDate"]["year"],
                    manga["averageScore"],
                    manga["popularity"]
                ])
    except Exception as e:
        print(f"Error saving to CSV: {e}")
        

manga_list = fetch_manga()
save_to_csv(manga_list)
print("Manga data saved to manga.csv")