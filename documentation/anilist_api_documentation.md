# Anilist Documentation Discussion
This file is for future me, I came back to this project after so long and had to spend extra time working on understanding the structure of the API and GraphQL therefore I'll document my problems and my current understanding of this recommendation engine so that the future me can work upon this better


## References
This is the documentation page for the root query
https://docs.anilist.co/reference/query

This is the documentation page Im using to get the media parameters for the query
https://docs.anilist.co/reference/object/media


## The Journey of Scaling the Ingestion Pipeline

### First Attempt: Basic Pagination (`page += 1`)
When I first started writing this scraper, I used standard page-based pagination. I set up a loop that simply requested 50 items per page and incremented the page variable (`page += 1`) until `hasNextPage` returned false. This worked perfectly for a while, but it crashed hard when it reached page 101 of year 2016. I ran into a strict 5,000-record query depth limit enforced by the AniList GraphQL API, which returns a 400 Bad Request if you try to query any page beyond page 100. Moreover, I hit the limit faster than my previous attempt, because I was requesting more data like relations. 

### Attempt number 1.5: The ID Attempt
My next thought was to bypass page limits by paginating using entity IDs. Since IDs increment monotonically, I wanted to query items page-by-page by filtering for IDs greater than the last fetched ID. However, the AniList root query doesn't natively support range filtering on IDs (like `id_greater` or similar parameters) in combination with the complex media parameters I needed. Paginating by ID was not a valid solution.

### The proper Second Attempt: Transition to Date Range Sharding
Since ID filtering wasn't an option, I decided to shard the dataset using time ranges. I switched the query parameters to filter by date windows using `startDate_greater` and `startDate_lesser` fuzzy integers (rough approximations of the timestamp). The plan was to isolate data into smaller time windows (like a year or a month) so that the total count of matching items in any single window would stay safely below the 5,000-record threshold, allowing page-based queries to finish before hitting page 101.

### The Third Attempt: Dealing with Spikes and the Duplication Trap
Even with date ranges, I ran into issues. Certain time periods—specifically timeperiods startinf from early 2016—had massive spikes of titles (over 5,000) because many titles default to start dates of `YYYY-00-00` or `YYYY-01-01` in the database when the exact date is unknown. To handle these spikes, I built dynamic range splitting: if a range threw a page depth error on page 101, the script caught the exception, split the date window in half, and processed the sub-ranges.

However, this created a major duplication bug. The script was stream-writing directly to `raw_data.csv` page-by-page. When a range reached page 100 and then failed on page 101, it had already appended 5,000 records to the CSV file. After catching the error and splitting the range, the script started fetching and writing those same records again from page 1 of the sub-ranges. This led to dirty writes, duplicating some titles up to five times in the CSV.

### The Fourth Attempt: Transactional Memory Buffering & State Queue
To make the script resilient, I refactored the pipeline to use in-memory buffering. Now, instead of writing directly to the CSV, the script stores rows in a list buffer during a date range. 
* If the range completes successfully, the buffer is committed and written to `raw_data.csv` at once.
* If a page depth error is encountered, the buffer is discarded (acting as a transaction rollback), the range is split, and the split ranges are queued.

I also replaced the recursion stack with an iterative stateful queue stored as JSON in `api_progress_manga.txt`. This persists the exact pending tasks and page offsets across crashes, allowing the script to resume safely. 

Finally, I discovered that AniList's date filters are strictly exclusive (e.g. querying greater than `20160218` ignores Feb 18 itself). I solved this date boundary issue by subtracting 1 day from the start range and adding 1 day to the end range when querying, making the queries behave inclusively.
