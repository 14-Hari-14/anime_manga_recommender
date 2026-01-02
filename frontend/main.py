import streamlit as st
import requests

# imports the list of filter tags from config_public
from config_public import (
    FORMAT_TAGS_CONFIRMED,
    GENRE_TAGS_CONFIRMED,
    THEME_TAGS_CONFIRMED,
    CONTENT_WARNINGS_CONFIRMED,
    GENDER_SPECIFIC_TAGS
)

# custom styling
st.set_page_config(page_title="Manga Recommender", layout="wide")

def set_custom_style():
    st.markdown("""
        <style>
        /* Hide default Streamlit clutter */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        
        /* Adjust padding */
        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
        }
        
        /* CUSTOM BUTTONS: MangaDex Orange */
        div.stButton > button {
            background-color: #FF6740; /* Orange */
            color: white;
            border-radius: 4px; /* Sharper corners like MangaDex */
            border: none;
            padding: 0.5rem 2rem;
            font-weight: bold;
            width: 100%;
            transition: all 0.2s;
        }
        div.stButton > button:hover {
            background-color: #E55B36; /* Darker Orange on hover */
            color: white;
            border: none;
            transform: scale(1.02);
        }
        
        /* INPUT FIELDS: Darker background to match theme */
        .stTextInput > div > div > input {
            background-color: #242634;
            color: #FAFAFA;
            border-color: #444;
        }
        </style>
    """, unsafe_allow_html=True)

set_custom_style()

# hero section
st.markdown("""
    <div style="text-align: center; margin-bottom: 40px;">
        <h1 style="font-size: 3.5em; margin-bottom: 10px;">Manga & Anime Recommender</h1>
    </div>
""", unsafe_allow_html=True)

# sidebar filters
with st.sidebar:
    st.header("🔍 Filters")
    content_type = st.multiselect("Type", ["Anime", "Manga"], default=["Manga"])
    format = st.multiselect("Format", FORMAT_TAGS_CONFIRMED)
    genres = st.multiselect("Genres", GENRE_TAGS_CONFIRMED)
    
    st.divider()
    
    st.subheader("Themes")
    hard_limit = st.multiselect("Must Have (Strict)", THEME_TAGS_CONFIRMED)
    soft_limit = st.multiselect("Good to Have (Boost)", THEME_TAGS_CONFIRMED)
    banned_tags = st.multiselect("Exclude Tags", THEME_TAGS_CONFIRMED)
    
    st.divider()
    
    st.subheader("Other")
    view_desc = st.multiselect("Viewer Discretion", CONTENT_WARNINGS_CONFIRMED)
    demo = st.multiselect("Demographic", GENDER_SPECIFIC_TAGS)
    
    st.toggle("Allow NSFW Content", key="nsfw_toggle")
    st.markdown("Note: Turning this on might include 18+ content in the recommendations.")

# main input area
query = st.text_input(
    "Describe what you want to read:", 
    placeholder="e.g., 'An isekai where the MC uses strategy instead of brute force...'"
)

if st.button("Get Recommendations"):

    if not query.strip():
        st.warning("⚠️ Please enter a description.")
        st.stop()
        
    payload = {
        "query": query,
        "content_type": content_type,
        "format": format,
        "genre": genres,
        "hard_limit": hard_limit,
        "soft_limit": soft_limit,
        "banned_tags": banned_tags,
        "viewer_descretion": view_desc,
        "demographic": demo,
        "allow_nsfw": st.session_state.nsfw_toggle
    }
    
    print("nsfw state: ", st.session_state.nsfw_toggle)

    with st.spinner("Analyzing vectors & reranking results..."):
        try:
            response = requests.post(
                "http://localhost:8000/recommend",
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            results = response.json()

        except requests.exceptions.RequestException as e:
            st.error(f"Backend error: {e}")
            st.stop()

    # result display (html cards)
    if not results:
        st.info("No recommendations found matching your criteria.")
    else:
        st.success(f"Found {len(results)} top matches:")
        
        for idx, item in enumerate(results, 1):
            # Safe fallbacks
            img_url = item.get("image_url") 
            if not img_url or img_url == "NA":
                img_url = "https://via.placeholder.com/150?text=No+Image"
                
            title = item['title']
            desc = item['description'][:250] + "..." if item['description'] else "No description available."
            score = item.get('average_score', 'N/A')
            popularity = item.get('popularity', 'N/A')
            
            # Create tags HTML
            tags_html = "".join([
                f'<span style="background-color: #242634; color: #EEE; padding: 4px 8px; border-radius: 4px; font-size: 0.8em; margin-right: 6px;">{t}</span>' 
                for t in sorted(item.get("tags", []))
            ])

            
            html_code = f"""
<div style="background-color: #242634; padding: 20px; border-radius: 12px; margin-bottom: 25px; display: flex; gap: 25px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); border: 1px solid #333;">
    <div style="flex: 0 0 160px;">
        <img src="{img_url}" style="width: 100%; border-radius: 8px; object-fit: cover;">
    </div>
    <div style="flex: 1;">
        <div style="display: flex; justify-content: space-between; align-items: start;">
            <h3 style="margin-top: 0; margin-bottom: 5px; color: #FFF;">{idx}. {title}</h3>
            <span style="background-color: #FF4B4B; color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 0.9em;">★ {score}</span>
        </div>
        <p style="color: #AAA; font-size: 0.9em; margin-bottom: 10px;">❤️ {popularity} users have this listed</p>
        <p style="color: #DDD; font-size: 1em; line-height: 1.5; margin-bottom: 15px;">{desc}</p>
        <div>{tags_html}</div>
    </div>
</div>
"""
            st.markdown(html_code, unsafe_allow_html=True)