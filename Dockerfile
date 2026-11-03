FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py browser_inputs.py pvt_engine.py fit_engine.py serve.py ./
COPY templates ./templates
COPY static ./static
RUN useradd --create-home appuser
USER appuser
ENV HOST=0.0.0.0 PORT=8050 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8050
CMD ["python", "serve.py"]
