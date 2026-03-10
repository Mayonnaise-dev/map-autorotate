FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install rcon requests

# Copy the script
COPY autorotate.py .

# Run the script unbuffered so logs show up in Docker instantly
CMD ["python", "-u", "autorotate.py"]