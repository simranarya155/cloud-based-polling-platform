# Use official Python image
FROM python:3.11-slim

# set workdir
WORKDIR /app

# copy requirements then install (layer caching)
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# copy application code
COPY . .

# tell gunicorn to bind to $PORT
CMD exec gunicorn --bind :$PORT --workers 2 --threads 4 app:app
