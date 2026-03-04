# Use official Python image
FROM python

# Set working directory
WORKDIR /app

# Copy application code
COPY . .

# Default command
CMD ["python", "app.py"]
