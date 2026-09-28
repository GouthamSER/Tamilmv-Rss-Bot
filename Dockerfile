# Use an official lightweight Python runtime
FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /app

# Ensure Python output and logs are sent straight to terminal/docker logs without buffering
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies (optional, safe defaults)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements if available, or install dependencies
COPY requirements.txt* ./
RUN pip install --no-cache-dir --upgrade pip && \
    if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; else pip install --no-cache-dir flask; fi

# Copy the rest of your application code into the container
COPY . .

# Expose the port Flask runs on (default is 8000, overridden by $PORT)
EXPOSE 5090

# Command to run your bot script
CMD ["python3", "bot.py"]

