# This script is used to query Anilist API for the anime and manga titles and create a csv
import requests
import csv
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Dict
import json

ANILIST_URL = "https://graphql.anilist.co"
BASE_DIR = Path(__file__).resolve().parent

OUTPUT_FILE= BASE_DIR.parent / "data" / "raw_data.csv"

# the paging limit of 5000 was crashing the script so i switched over to time based sharding 
START_DATE = date(1950, 1, 1)
END_DATE = date(2026, 12, 31)

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
query ($page: Int, $perPage: Int, $mediaType: MediaType!, $startDateGreater: FuzzyDateInt, $startDateLesser: FuzzyDateInt) {
  Page(page: $page, perPage: $perPage) {
	pageInfo {
	  hasNextPage
	  currentPage
	}
	media(type: $mediaType, startDate_greater: $startDateGreater, startDate_lesser: $startDateLesser) {
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

# Serializes the queue of pending date ranges to the progress file in JSON format.
def save_progress(progress_file: Path, pending_list: list[dict[str, Any]]) -> None:
	ensure_parent_dir(progress_file)
	serialized = []
	for item in pending_list:
		serialized.append({
			"start": item["start"].isoformat(),
			"end": item["end"].isoformat(),
			"page": item.get("page", 1)
		})
	progress_file.write_text(json.dumps(serialized, indent=2), encoding="utf-8")


# Loads the pending date ranges from the progress file, supporting legacy comma-separated formats for backwards compatibility.
def load_progress(progress_file: Path) -> list[dict[str, Any]]:
	if progress_file.exists():
		raw_content = progress_file.read_text(encoding="utf-8").strip()
		if raw_content:
			try:
				# Try loading as JSON list (new format)
				data = json.loads(raw_content)
				if isinstance(data, list):
					parsed = []
					for item in data:
						parsed.append({
							"start": date.fromisoformat(item["start"]),
							"end": date.fromisoformat(item["end"]),
							"page": item.get("page", 1)
						})
					return parsed
			except json.JSONDecodeError:
				pass

			# Fallback/Backward compatibility for legacy format
			if "," in raw_content:
				first, second = raw_content.split(",", 1)
				if len(first) == 4 and first.isdigit() and second.isdigit():
					year = int(first)
					return [{"start": date(year, 1, 1), "end": date(year, 12, 31), "page": 1}]
				return [{"start": date.fromisoformat(first), "end": date.fromisoformat(second), "page": 1}]
			elif len(raw_content) == 4 and raw_content.isdigit():
				year = int(raw_content)
				return [{"start": date(year, 1, 1), "end": date(year, 12, 31), "page": 1}]

	return [{"start": START_DATE, "end": END_DATE, "page": 1}]


# Converts a date object to an integer in YYYYMMDD format expected by the AniList API.
def date_to_fuzzy_int(value: date) -> int:
	return int(value.strftime("%Y%m%d"))


# Splits a date range in half, returning two adjacent date ranges for sharding.
def split_date_range(start_value: date, end_value: date) -> tuple[date, date] | None:
	if start_value >= end_value:
		return None

	middle = start_value + timedelta(days=(end_value - start_value).days // 2)
	left_end = middle
	right_start = middle + timedelta(days=1)

	if left_end < start_value or right_start > end_value or left_end >= right_start:
		return None

	return left_end, right_start


# Checks if an API error is due to requesting a page beyond the maximum depth of 5000 entries.
def is_page_depth_error(error: Exception) -> bool:
	return "Page depth exceeds maximum allowed for API requests (5000 entries)" in str(error)


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


# Maps raw AniList API media fields to a structured flat dictionary representing a single CSV row.
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

# Iteratively processes the queue of pending date ranges, buffering pages in memory and writing to CSV only on successful completion of a range.
def ingest_media_by_type(session: requests.Session, writer: csv.DictWriter, media_type: str, progress_file: Path, per_page: int = 50) -> None:
	pending = load_progress(progress_file)

	# Ensure progress is stored in new format immediately on load
	save_progress(progress_file, pending)

	while pending:
		# Peek at the current active range
		current = pending[0]
		start_value = current["start"]
		end_value = current["end"]
		page = current.get("page", 1)

		print(f"Processing {media_type} range {start_value} to {end_value} starting from page {page}...")

		range_failed_depth = False
		buffer = []
		while True:
			# Subtracting 1 day and adding 1 day makes the query boundaries inclusive,
			# since AniList's API greater/lesser filters are exclusive.
			variables = {
				"page": page,
				"perPage": per_page,
				"mediaType": media_type,
				"startDateGreater": date_to_fuzzy_int(start_value - timedelta(days=1)),
				"startDateLesser": date_to_fuzzy_int(end_value + timedelta(days=1)),
			}

			try:
				page_data = post_graphql(session, variables)["data"]["Page"]
			except (requests.HTTPError, RuntimeError) as error:
				if is_page_depth_error(error):
					range_failed_depth = True
					break
				raise

			media_items = page_data["media"] or []
			if not media_items:
				break

			for media in media_items:
				row = build_row(media)
				buffer.append(row)

			print(f"Successfully processed page {page} for {media_type} shard {start_value} to {end_value}")

			page += 1
			current["page"] = page
			save_progress(progress_file, pending)

			if not page_data["pageInfo"]["hasNextPage"]:
				break

			time.sleep(2.2)

		if range_failed_depth:
			split_window = split_date_range(start_value, end_value)
			if split_window is None:
				raise RuntimeError(f"Cannot split date range further: {start_value} to {end_value}")

			left_end, right_start = split_window
			print(f"Splitting {media_type} shard {start_value} to {end_value} into {start_value} to {left_end} and {right_start} to {end_value}")

			# Remove the current range, insert the split halves to the front of the queue, and save progress
			pending.pop(0)
			pending.insert(0, {"start": right_start, "end": end_value, "page": 1})
			pending.insert(0, {"start": start_value, "end": left_end, "page": 1})
			save_progress(progress_file, pending)
		else:
			print(f"Completed {media_type} range {start_value} to {end_value} successfully! Writing {len(buffer)} items to CSV.")
			for row in buffer:
				writer.writerow(row)
			pending.pop(0)
			save_progress(progress_file, pending)
            
# Coordinates the ingestion process by initializing the HTTP session, CSV writer, and calling the type-specific ingestion.
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