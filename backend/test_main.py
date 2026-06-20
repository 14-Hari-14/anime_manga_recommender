import pytest
import sqlite3
import json
from fastapi.testclient import TestClient

# Import functions to be tested from main
from main import app, parse_tags_genres, sanitize_fts_query, resolve_chain

# ==============================================================================
# 1. UNIT TESTING (PURE FUNCTIONS)
# ==============================================================================
# Rule of thumb: Unit tests should test pure functions under various inputs 
# (valid, empty, edge-case, and malformed) to ensure they handle failures gracefully.

def test_parse_tags_genres_valid():
    """Test standard stringified python lists."""
    raw_list_single = "['Drama', 'Comedy']"
    raw_list_double = '["Fantasy", "Action"]'
    
    assert parse_tags_genres(raw_list_single) == ["Drama", "Comedy"]
    assert parse_tags_genres(raw_list_double) == ["Fantasy", "Action"]

def test_parse_tags_genres_edge_cases():
    """Test empty, None, and malformed inputs."""
    assert parse_tags_genres("") == []
    assert parse_tags_genres(None) == []
    assert parse_tags_genres("[]") == []
    # Malformed inputs should not crash the program, but return whatever is splitable
    assert parse_tags_genres("Action, Comedy") == ["Action", "Comedy"]


# ==============================================================================
# 2. PARAMETERIZED TESTING
# ==============================================================================
# Rule of thumb: If you are testing the same function with multiple inputs/outputs,
# use pytest's @pytest.mark.parametrize to keep your test code DRY (Don't Repeat Yourself).

@pytest.mark.parametrize("input_query,expected_output", [
    ("dark fantasy magic", "dark OR fantasy OR magic"),
    ("sword & shield!", "sword OR shield"),
    ("Attack on Titan", "attack OR titan"),  # "on" is a stopword and is removed
    ("in on with", "in OR on OR with"),      # If only stopwords are present, fallback to them
    ("", ""),                                # Empty string
    ("   ", ""),                             # Whitespace only
])
def test_sanitize_fts_query(input_query, expected_output):
    """Verify stop-word stripping and FTS formatting rules."""
    assert sanitize_fts_query(input_query) == expected_output


# ==============================================================================
# 3. DATABASE TESTING (USING IN-MEMORY DATABASE FIXTURES)
# ==============================================================================
# Rule of thumb: Never run tests against your production database. Instead,
# use a pytest fixture to set up a temporary in-memory database populated with 
# seed data, test against it, and let pytest tear it down automatically.

@pytest.fixture
def mock_db():
    """Creates a temporary in-memory database populated with mock franchise relations."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    
    # 1. Create a dummy media table mimicking the production schema
    cursor.execute("""
        CREATE TABLE media (
            id INTEGER PRIMARY KEY,
            title TEXT,
            relations TEXT
        )
    """)
    
    # 2. Populate with a mock franchise:
    # Title A (ID 1) -> prequel to Title B (ID 2) -> prequel to Title C (ID 3)
    # Title D (ID 4) -> Adaptation/Other connection to Title B (ID 2)
    relations_a = json.dumps([{"relationType": "SEQUEL", "node": {"id": 2, "title": {"english": "Title B"}}}])
    relations_b = json.dumps([
        {"relationType": "PREQUEL", "node": {"id": 1, "title": {"english": "Title A"}}},
        {"relationType": "SEQUEL", "node": {"id": 3, "title": {"english": "Title C"}}},
        {"relationType": "ADAPTATION", "node": {"id": 4, "title": {"english": "Title D"}}}
    ])
    relations_c = json.dumps([{"relationType": "PREQUEL", "node": {"id": 2, "title": {"english": "Title B"}}}])
    relations_d = json.dumps([{"relationType": "ADAPTATION", "node": {"id": 2, "title": {"english": "Title B"}}}])
    
    cursor.executemany("INSERT INTO media (id, title, relations) VALUES (?, ?, ?)", [
        (1, "Title A", relations_a),
        (2, "Title B", relations_b),
        (3, "Title C", relations_c),
        (4, "Title D", relations_d)
    ])
    conn.commit()
    
    yield conn
    conn.close()

def test_resolve_chain_traversal(mock_db):
    """Verify that resolve_chain correctly traverses prequel and sequel links."""
    # We query from Title B (ID 2)
    chain, other_relations, visited_ids = resolve_chain(mock_db, start_id=2, start_title="Title B")
    
    # Chronological progression should show: Title A -> Title B -> Title C
    assert chain == ["Title A", "Title B", "Title C"]
    
    # Other relations should extract Title D
    assert other_relations == ["ADAPTATION: Title D"]
    
    # Visited IDs should contain all nodes in the chain
    assert visited_ids == {1, 2, 3}


# ==============================================================================
# 4. API ROUTE TESTING (INTEGRATION)
# ==============================================================================
# Rule of thumb: Use FastAPI's TestClient to verify the HTTP request/response contract.
# Test for input validation, expected status codes, and return body structures.

@pytest.fixture
def api_client():
    """Returns a FastAPI TestClient."""
    return TestClient(app)

def test_recommend_validation_empty_content_type(api_client):
    """Sending an empty content_type list should return an empty list immediately."""
    response = api_client.post("/recommend", json={
        "query": "some query",
        "content_type": []
    })
    assert response.status_code == 200
    assert response.json() == []

def test_recommend_empty_query_fallback(api_client):
    """Verify that sending an empty query returns recommendations without crashing."""
    response = api_client.post("/recommend", json={
        "query": "",
        "content_type": ["manga"],
        "min_score": 50,
        "max_score": 100
    })
    assert response.status_code == 200
    results = response.json()
    assert isinstance(results, list)
    # It should return at most 20 recommendations
    assert len(results) <= 20
    if results:
        # Check that result schema matches RecommendationItem
        item = results[0]
        assert "title" in item
        assert "bucket" in item
        assert "average_score" in item


# ==============================================================================
# 5. YOUR EXERCISES (OBJECTIVES FOR YOU TO COMPLETE!)
# ==============================================================================
# Objective 1: Write a unit test for `fetch_metadata_by_db_ids`.
#   - Create a mock database with 2 rows.
#   - Call `fetch_metadata_by_db_ids` and assert it returns a dictionary keyed by DB id.
#
# Objective 2: Write a test that verifies the NSFW filter behavior.
#   - Try passing a payload with nsfw_allowed=False vs nsfw_allowed=True.
#   - Assert that no titles containing forbidden adult tags are returned when disabled.
