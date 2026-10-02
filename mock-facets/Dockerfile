FROM python:3.12-slim
WORKDIR /srv
RUN useradd --create-home appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mock_facets ./mock_facets
USER appuser
EXPOSE 8001
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8001/health')"
CMD ["uvicorn", "mock_facets.main:app", "--host", "0.0.0.0", "--port", "8001"]
