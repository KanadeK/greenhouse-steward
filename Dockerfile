FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN python -m pip install --no-cache-dir .
EXPOSE 8000
ENTRYPOINT ["greenhouse-steward", "serve", "--host", "127.0.0.1", "--port", "8000"]
