# Anime & Manga Recommendation System

A sophisticated recommendation engine that leverages vector embeddings and semantic search to provide personalized anime and manga recommendations based on natural language queries and user preferences.

## Features

- **Semantic Search**: Uses SentenceTransformers to understand natural language queries
- **Dual Content Support**: Recommendations for both anime and manga
- **Advanced Filtering**: Support for genres, tags, content warnings, and demographic filters
- **Re-ranking System**: Intelligent re-ranking algorithm to refine recommendations
- **Fast Vector Search**: FAISS-based indexing for efficient similarity searches
- **User-Friendly Interface**: Streamlit-powered web application with customizable styling

## Project Structure

### `/backend`

FastAPI-based recommendation engine that handles all the recommendation logic and searching.

**Key Files:**

- `main.py` - FastAPI application with recommendation endpoints
- `reranking_results.py` - Post-processing logic to refine and rank recommendations

**Functionality:**

- Accepts natural language queries and filter preferences
- Performs semantic similarity search using FAISS indices
- Applies tag-based filtering (hard tags, soft tags, banned tags)
- Returns ranked recommendations with metadata

### `/frontend`

Streamlit-based web interface for user interaction with the recommendation system.

**Key Files:**

- `main.py` - Streamlit application interface
- `config.toml` - Theme and styling configuration (MangaDex-inspired design)
- `config_public.py` - Filter options and confirmed tags

**Features:**

- Interactive query input
- Advanced filtering UI for genres, tags, and content warnings
- Real-time recommendations display
- Responsive design with custom styling

### `/data`

Contains all data assets and trained models.

**Structure:**

- `cleaned_anime_collections_with_combined_text.csv` - Processed anime dataset
- `cleaned_manga_collections_with_combined_text.csv` - Processed manga dataset
- `genres_tags/` - Reference files with unique genres and tags
  - `unique_anime_genres.txt` - Available anime genres
  - `unique_anime_tags.txt` - Available anime tags
  - `unique_manga_genres.txt` - Available manga genres
  - `unique_manga_tags.txt` - Available manga tags
- `vector_stores/` - Pre-trained FAISS indices and embeddings
  - `anime_index.faiss` - FAISS index for anime embeddings
  - `manga_index.faiss` - FAISS index for manga embeddings
  - `embeddings_anime.npy` - Anime embedding vectors
  - `embeddings_manga.npy` - Manga embedding vectors

### `/scripts`

Utility scripts for data processing, database management, and model training.

**Key Scripts:**

- `create_sqlite_db.py` - Initialize SQLite database from CSV files
- `clean_db.py` - Database cleanup and maintenance utilities
- `get_anime_script.py` - Data collection script for anime
- `get_manga_script.py` - Data collection script for manga
- `test_model.py` - Model testing and validation
- `recommendation_system_revamped.ipynb` - Jupyter notebook for system development and analysis

**Subdirectory:**

- `redundant_scripts/` - Legacy and obsolete scripts for reference

## Getting Started

### Prerequisites

- Python 3.8+
- FastAPI
- Streamlit
- FAISS
- SentenceTransformers
- SQLite3
- Pandas/NumPy

### Installation

1. Clone the repository:

```bash
git clone <repository-url>
cd recommendation_system_new
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

### Running the System

**Generate the csv files by calling the ANILIST api**

- Run the get_anime_script.py
- Run the get_manga_script.py

- Run the recommendation_system_revamped.py file preferrably in google collab with t4 gpu runtime environment to quickly get the vector store of embeddings

- Run the create_sqlite_db.py to create the sqlite db
- Run the clean_db.py script to fix the tags and genres columns

- Optional: run the test_model.py to see if the whole process is working

**Start the Backend Server:**

```bash
cd backend
python main.py
# or with uvicorn
uvicorn main:app --reload
```

**Start the Frontend Application:**

```bash
cd frontend
streamlit run main.py
```

The frontend will typically be available at `http://localhost:8501` and the backend at `http://localhost:8000`.

## Usage

1. Open the Streamlit interface
2. Enter a natural language query (e.g., "I want an action-packed anime with great animation")
3. Select content types (Anime, Manga, or both)
4. Apply optional filters:
   - Format preferences
   - Hard tags (must include)
   - Soft tags (preferred)
   - Banned tags (must exclude)
5. View personalized recommendations with metadata

## How It Works

1. **Query Embedding**: User input is converted to a semantic vector using SentenceTransformers
2. **Vector Search**: FAISS indices are searched to find semantically similar content
3. **Filtering**: Results are filtered based on user preferences and tag constraints
4. **Re-ranking**: The ReRanker applies post-processing to optimize final recommendations
5. **Results**: Ranked recommendations are returned with relevant metadata

## Data Processing Pipeline

- Raw anime/manga data is collected via scraping scripts
- Data is cleaned and deduplicated
- Text is combined from multiple fields for semantic understanding
- Embeddings are generated and indexed in FAISS
- Genre and tag references are maintained for filtering
