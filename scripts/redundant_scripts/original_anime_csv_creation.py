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
    media(type: ANIME, sort: POPULARITY_DESC) {
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
def fetch_anime(max_pages=5, per_page=50):
    all_anime = []

    # loop through pages to get all anime
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

        all_anime.extend(media)
        time.sleep(1)  

    return all_anime

def save_to_csv(anime_list, filename="anime.csv"):
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

            for anime in anime_list:
                writer.writerow([
                    anime["id"],
                    anime["title"]["english"] or anime["title"]["romaji"],
                    anime["description"],
                    ",".join(anime["genres"]),
                    ",".join([t["name"] for t in anime["tags"]]),
                    anime["startDate"]["year"],
                    anime["averageScore"],
                    anime["popularity"]
                ])
    except Exception as e:
        print(f"Error saving to CSV: {e}")
        

anime_list = fetch_anime()
save_to_csv(anime_list)
print("Anime data saved to anime.csv")