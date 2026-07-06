FROM python:3.12-slim

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=8042

EXPOSE 8042

CMD ["python", "server.py"]
