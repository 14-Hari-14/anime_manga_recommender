import requests
import csv
import time
import os
from pathlib import Path
from typing import Any, Iterable, Dict
import json

ANILIST_URL = "https://graphql.anilist.co"
BASE_DIR = Path(__file__).resolve().parent

OUTPUT_FILE= BASE_DIR.parent / "data" / "raw_data.csv"

# The difference in output file and progress file is because 
# anilist segregates data on the basis of anime and manga 
# and there are no special categories for manhua or manhwa 
# so i would have to separate them based on country of origin

PROGRESS_FILE_ANIME = BASE_DIR.parent / "data" / "api_progress_anime.txt"
PROGRESS_FILE_MANGA = BASE_DIR.parent / "data" / "api_progress_manga.txt"

# Headers to be written for files
CSV_HEADERS = [
	"id",
	"bucket",
	"media_type",
	"title",
	"native_title",
	"description",
	"country_of_origin",
	"format",
	"status",
	"year",
	"average_score",
	"popularity",
	"genres",
	"tags",
	"synonyms",
	"relations",
	"image_url",
	"is_adult",
]

# modifying description asHtml argument as false to reduce the amount of cleaning required for descriptions
# relation has edges(relationType) -> to show prequel sequels ova and node is the datatype which describes any title
# countryOfOrigin: to separate manga, manhwa and manhua for better filtering
QUERY = """
query ($page: Int, $perPage: Int, $mediaType: MediaType!) {
  Page(page: $page, perPage: $perPage) {
	pageInfo {
	  hasNextPage
	  currentPage
	}
	media(type: $mediaType) {
	  id
	  type
	  title {
		romaji
		english
		native
	  }
	  description(asHtml: false) 
	  countryOfOrigin
	  format
	  status
	  genres
	  synonyms
	  tags {
		name
		rank
	  }
	  relations {
		edges {
		  relationType
		  node {
			id
			type
			countryOfOrigin
			format
			status
			title {
			  romaji
			  english
			  native
			}
			siteUrl
		  }
		}
	  }
	  coverImage {
		extraLarge
	  }
	  averageScore
	  popularity
	  startDate {
		year
	  }
	  isAdult
	}
  }
}
"""

# Check if parent directory exists if it doesnt make them
def ensure_parent_dir(path: Path) -> None:
	path.parent.mkdir(parents=True, exist_ok=True) # dont raise error if the dir already exists


# Retrieve the value from progress file if it exists or return 1 as start
def load_last_page(progress_file: Path) -> int:
	if progress_file.exists():
		raw_value = progress_file.read_text(encoding="utf-8").strip()
		if raw_value:
			return int(raw_value)
	return 1

# Overwrite the previous value to store the current page value
def save_progress(progress_file: Path, page: int) -> None:
	ensure_parent_dir(progress_file)
	progress_file.write_text(str(page), encoding="utf-8")


# To clean and get the description into a unified format
def normalize_text(value: str | None) -> str:
	if value is None:
		return ""
	return str(value).replace("\r", " ").replace("\n", " ").strip()

# CSV files cant store lists so we transform the iterable data types to strings (genres/tags) and transform them again when required using split
def normalize_list(values: Iterable[Any] | None) -> str:
      if values is None:
            return ""
      return ",".join(normalize_text(value) for value in values if normalize_text(value)) # join requires string only + filter out empty strings


# Relation is a dictionary mapping with key being edges and node being the value 
# The function uses edges to extract each node and then converts that iterable into string format while maintaining the relationship
# This doesnt maintain chronology but I will handle that later using relationType(which classifies title as prequel, sequel, side story, spinoff etc) and using that I can do graph traversal maybe
def normalize_relations(relations: Dict[str, Any] | None) -> str:
	if not relations:
		return ""

	edges = []
	for edge in relations.get("edges", []):
		node = edge.get("node") or {}
		edges.append(
			{
				"relationType": edge.get("relationType"),
				"node": {
					"id": node.get("id"),
					"type": node.get("type"),
					"countryOfOrigin": node.get("countryOfOrigin"),
					"format": node.get("format"),
					"status": node.get("status"),
					"title": {
						"romaji": (node.get("title") or {}).get("romaji"),
						"english": (node.get("title") or {}).get("english"),
						"native": (node.get("title") or {}).get("native"),
					},
					"siteUrl": node.get("siteUrl"),
				},
			}
		)

	return json.dumps(edges, ensure_ascii=False)

# Properly extract and clean the title and native title
def select_title(title_block: Dict[str, Any] | None) -> tuple[str, str]:
	title_block = title_block or {}
	title = title_block.get("english") or title_block.get("romaji") or title_block.get("native") or "Unknown Title"
	native_title = title_block.get("native") or ""
	return title, native_title

# This will help filter between manga, manhwa and manhua using country of origin since there isnt a native method to do so in the anilist api
def classify_bucket(media: Dict[str, Any]) -> str:
	media_type = (media.get("type") or "").upper()
	country_of_origin = (media.get("countryOfOrigin") or "").upper()

	if media_type == "ANIME":
		return "anime"

	if country_of_origin == "KR":
		return "manhwa"

	if country_of_origin == "CN" or country_of_origin=="TW":
		return "manhua"

	return "manga"


def build_row(media: Dict[str, Any]) -> Dict[str, Any]:
	title, native_title = select_title(media.get("title"))
	image_url = (media.get("coverImage") or {}).get("extraLarge") or "NA"

	return {
		"id": media.get("id"),
		"bucket": classify_bucket(media),
		"media_type": media.get("type") or "",
		"title": title,
		"native_title": native_title,
		"description": normalize_text(media.get("description")),
		"country_of_origin": media.get("countryOfOrigin") or "",
		"format": media.get("format") or "",
		"status": media.get("status") or "",
		"year": (media.get("startDate") or {}).get("year") or "",
		"average_score": media.get("averageScore") or 0,
		"popularity": media.get("popularity") or 0,
		"genres": normalize_list(media.get("genres")),
		"tags": normalize_list((tag.get("name") for tag in media.get("tags", []))),
		"synonyms": normalize_list(media.get("synonyms")),
		"relations": normalize_relations(media.get("relations")),
		"image_url": image_url,
		"is_adult": bool(media.get("isAdult", False)),
}

# to actually interact with the api and properly call and handle all the functions made till now
def post_graphql(session: requests.Session, variables: Dict[str, Any], max_retries: int = 5) -> Dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            response = session.post(
                ANILIST_URL,
                json={"query": QUERY, "variables": variables},
                timeout=30,
            )

            # Anilist has specified that they will provide the time period
            #  after which we can retry hitting the api in the documentation after a 429 error
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After") # get time limit after which retry should happen
                
                if retry_after:
                    sleep_seconds = int(retry_after) + 1  # Add 1s safety buffer
                    print(f" Rate Limited! AniList explicitly requested a pause of {retry_after}s.")
                else:
                    sleep_seconds = 61  # Fallback to AniList's standard 1-minute ban
                    print(" Rate Limited! Header missing, defaulting to a 61s pause.")

                print(f"Sleeping for {sleep_seconds}s before retrying page {variables['page']}...")
                time.sleep(sleep_seconds)
                continue  # Retry the loop without counting this as a failed server attempt

            # Handle other temporary server errors using backoff
            if response.status_code in {500, 502, 503, 504}:
                raise requests.HTTPError(f"Temporary server error: {response.status_code}")
            
            if response.status_code == 400:
                print(f"400 error response body: {response.text}")
                raise requests.HTTPError(f"Bad request: {response.text}")
            # Check for standard HTTP errors (like 400 Bad Request)
            response.raise_for_status()
            
            payload = response.json()

            # Check for internal GraphQL validation errors
            if payload.get("errors"):
                raise RuntimeError(f"GraphQL Error: {payload['errors']}")

            return payload

        except Exception as error:
            last_error = error
            if attempt == max_retries - 1:
                raise

            # Exponential backoff purely for 5xx server issues
            sleep_seconds = 2 ** attempt
            print(f"Request failed for page {variables['page']} ({variables['mediaType']}), retrying in {sleep_seconds}s: {error}")
            time.sleep(sleep_seconds)

    raise last_error or RuntimeError("AniList request failed")

def open_writer(path: Path) -> tuple[Any, csv.DictWriter]:
	ensure_parent_dir(path)
	file_handle = path.open("a", newline="", encoding="utf-8")
	writer = csv.DictWriter(file_handle, fieldnames=CSV_HEADERS)

	if path.stat().st_size == 0:
		writer.writeheader()

	return file_handle, writer

#Fetches all pages for a single media type and writes to the unified writer.
def ingest_media_by_type(session: requests.Session, writer: csv.DictWriter, media_type: str, progress_file: Path, per_page: int = 50) -> None:
    
    page = load_last_page(progress_file)
    print(f"Starting ingestion for {media_type} from page {page}...")

    while True:
        variables = {
            "page": page,
            "perPage": per_page,
            "mediaType": media_type
        }

        # calling function to communicate with the api
        page_data = post_graphql(session, variables)["data"]["Page"]
        media_items = page_data["media"] or []

        if not media_items:
            print(f"No more data returned for {media_type}.")
            break

        for media in media_items:
            row = build_row(media)
            writer.writerow(row)

        print(f"Successfully processed page {page} for {media_type}")
        save_progress(progress_file, page)

        if not page_data["pageInfo"]["hasNextPage"]:
            print(f"Reached final page for {media_type}.")
            break

        page += 1
        time.sleep(2.2)  # anilist api mentioned keeping request rate 30 per minute
		
def ingest_all() -> None:
    ensure_parent_dir(OUTPUT_FILE)
    file_exists = OUTPUT_FILE.exists() and OUTPUT_FILE.stat().st_size > 0

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        
        if not file_exists:
            writer.writeheader()

        # Download all Anime
        ingest_media_by_type(session, writer, "ANIME", PROGRESS_FILE_ANIME)
            
        print("Anime completed")

        # Download all Manga/Manhwa/Manhua into the exact same file
        ingest_media_by_type(session, writer, "MANGA", PROGRESS_FILE_MANGA)

if __name__ == "__main__":
    ingest_all()
    print("Full data ingestion complete!")