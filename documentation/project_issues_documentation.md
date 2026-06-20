# Anilist Documentation Discussion
This file is for future me. I came back to this project after so long and had to spend extra time working on understanding the structure of the API and GraphQL. Therefore, I'll document my problems and my current understanding of this recommendation engine so that the future me can work upon this better.

## References
- Root Query: https://docs.anilist.co/reference/query
- Media Parameters: https://docs.anilist.co/reference/object/media

---

## The Journey of Scaling the Ingestion Pipeline

### First Attempt: Basic Pagination (`page += 1`)
When I first started writing this scraper, I used standard page-based pagination. I set up a loop that simply requested 50 items per page and incremented the page variable (`page += 1`) until `hasNextPage` returned false. This worked perfectly for a while, but it crashed hard when it reached page 101 of year 2016. I ran into a strict 5,000-record query depth limit enforced by the AniList GraphQL API, which returns a 400 Bad Request if you try to query any page beyond page 100. Moreover, I hit the limit faster than my previous attempt because I was requesting more data like relations.

### Attempt number 1.5: The ID Attempt
My next thought was to bypass page limits by paginating using entity IDs. Since IDs increment monotonically, I wanted to query items page-by-page by filtering for IDs greater than the last fetched ID. HoIver, the AniList root query doesn't natively support range filtering on IDs (like `id_greater` or similar parameters) in combination with the complex media parameters I needed. Paginating by ID was not a valid solution.

### The proper Second Attempt: Transition to Date Range Sharding
Since ID filtering wasn't an option, I decided to shard the dataset using time ranges. I switched the query parameters to filter by date windows using `startDate_greater` and `startDate_lesser` fuzzy integers (rough approximations of the timestamp). The plan was to isolate data into smaller time windows (like a year or a month) so that the total count of matching items in any single window would stay safely below the 5,000-record threshold, allowing page-based queries to finish before hitting page 101.

### The Third Attempt: Dealing with Spikes and the Duplication Trap
Even with date ranges, I ran into issues. Certain time periods—specifically timeperiods starting from early 2016—had massive spikes of titles (over 5,000) because many titles default to start dates of `YYYY-00-00` or `YYYY-01-01` in the database when the exact date is unknown. To handle these spikes, I built dynamic range splitting: if a range threw a page depth error on page 101, the script caught the exception, split the date window in half, and processed the sub-ranges.

HoIver, this created a major duplication bug. The script was stream-writing directly to `raw_data.csv` page-by-page. When a range reached page 100 and then failed on page 101, it had already appended 5,000 records to the CSV file. After catching the error and splitting the range, the script started fetching and writing those same records again from page 1 of the sub-ranges. This led to dirty writes, duplicating some titles up to five times in the CSV.

### The Fourth Attempt: Transactional Memory Buffering & State Queue
To make the script resilient, I refactored the pipeline to use in-memory buffering. Now, instead of writing directly to the CSV, the script stores rows in a list buffer during a date range. 
* If the range completes successfully, the buffer is committed and written to `raw_data.csv` at once.
* If a page depth error is encountered, the buffer is discarded (acting as a transaction rollback), the range is split, and the split ranges are queued.

I also replaced the recursion stack with an iterative stateful queue stored as JSON in `api_progress_manga.txt`. This persists the exact pending tasks and page offsets across crashes, allowing the script to resume safely. 

Finally, I discovered that AniList's date filters are strictly exclusive (e.g. querying greater than `20160218` ignores Feb 18 itself). I solved this date boundary issue by subtracting 1 day from the start range and adding 1 day to the end range when querying, making the queries behave inclusively.

---

## Moving from multiple databases to a single database

Previously, the project operated on two separate databases and vector indexes for Anime and Manga, which required duplicating loading and query logic. Moreover to recommend titles in different format meant I would have to perform complex operations on the database to create custom views for each query, so instead I have switched over to the one file system, which thinking back should have been the default I should have opted for.

### Unifying the Data Source & Embeddings Script
To simplify maintenance, I unified all media files under `raw_data_clean.csv`. I updated `embeddings.ipynb` to process the unified dataset in a single linear flow without dividing it into Anime and Manga collections. This reduced the notebook length from 23 code cells to just 9.

### Database Indexing & clean_db.py Redundancy
The cleanup script `clean_db.py` was deprecated and rendered redundant because:
1. The ingestion script (`get_titles.py`) now normalizes lists (genres/tags) to clean, comma-separated strings during serialization. Brackets (`[` or `]`) and quotes are no longer written to the CSV.
2. In `create_sqlite_db.py`, the index creation for query optimization (`idx_faiss_id` and `idx_id`) is performed programmatically inside the database generator immediately after populating the table.


### Backend Refactoring
I refactored `backend/main.py` to load a single `unified_index.faiss` and connect to a unified `recommendations.db` (table `media`). I simplified the API inputs and removed the backward-compatibility mappings to enable native granular selections.

### Frontend Upgrades & relations Chain Traversal
Updated `frontend/main.py` to support granular type filtering (`anime`, `manga`, `manhwa`, `manhua`) and display the format type on each card.
Also resolved the relations visualization bug where only direct prequels/sequels Ire shown. The backend now recursively traverses SQLite entries to build the full chronological story progression chain (e.g., `AOT S1 ➔ AOT S2 ➔ (RECOMMENDED) AOT S3 ➔ AOT S4`).

---

## Project Roadmap (Todo List)

### Completed Tasks
- [x] Ingest Anime/Manga dynamically sharded by date ranges using transactional buffering.
- [x] Merge Anime/Manga CSVs and build a unified FAISS vector index.
- [x] Refactor database generation to write to a single unified SQLite database with indices.
- [x] Remove the redundant `clean_db.py` script.
- [x] Simplify backend mappings to connect to the unified FAISS index and database.
- [x] Support granular media type selection (`anime`, `manga`, `manhwa`, `manhua`) in the frontend.
- [x] Add the bucket category display under title cards.
- [x] Resolve full story progression chains recursively in the backend and display them visually.
- [x] Fix HTML indentation causing codeblocks (`</div>`) to render in Streamlit.
- [x] Fix hard/soft/banned tag filters by parsing stringified lists in the backend.
- [x] **Series Deduplication**: Collapse prequel/sequel relations of the same series in search results to keep the feed diverse.

### Future Work
- [ ] **Hybrid Search**: Combine FAISS dense search with BM25 sparse keyword search using Reciprocal Rank Fusion (RRF).
- [ ] **Cross-Encoder Re-ranking**: Integrate S-BERT Cross-Encoders (e.g. MS-MARCO) for deep semantic relevance check before tag filtering.
- [ ] **Query Expansion**: Implement synonym mappings and LLM-guided query expansion for search enrichment.
