# Optional LOCAL container recipe. Not verified in this delivery environment.
FROM python:3.11-slim
WORKDIR /app
COPY requirements-core.txt requirements-ml.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY frontend ./frontend
RUN useradd --create-home --uid 10001 desk && mkdir -p /app/data && chown -R desk:desk /app
USER desk
ENV OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
EXPOSE 8765
CMD ["python","-m","uvicorn","backend.main:app","--host","0.0.0.0","--port","8765","--loop","asyncio","--http","h11"]
