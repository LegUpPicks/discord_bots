FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install discord.py python-dotenv

COPY . .

CMD ["python", "purrcurity.py"]
