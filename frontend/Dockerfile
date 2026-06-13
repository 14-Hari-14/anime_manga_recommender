FROM python:3.10-slim

WORKDIR /app

# FIX 1: Point to the specific file in the frontend folder
COPY frontend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# This puts your code into /app/frontend/
COPY frontend/ /app/frontend/

EXPOSE 8501

# FIX 2: Point to the file inside the folder (frontend/main.py)
CMD ["streamlit", "run", "frontend/main.py", "--server.port=8501", "--server.address=0.0.0.0"]