FROM python:3.10-slim

# set working directory
WORKDIR /app/backend

# FIX: Copy from backend/requirements.txt
COPY backend/requirements.txt /app/requirements.txt

# install dependencies
RUN pip install --no-cache-dir -r /app/requirements.txt

# copy all backend files
COPY backend/ /app/backend/
# Copy the scripts too (needed for your data updates)
COPY scripts/ /app/scripts/

EXPOSE 8000

# command to run the app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]