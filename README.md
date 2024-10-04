# openai-realtime-api-fastapi-client

## Installation

Create a virtual environment and activate it:
```bash
python -m venv venv
source venv/bin/activate
```

Install the dependencies:
```bash
poetry install
```

## Setup OpenAI API key

Copy the `.env-template` file to `.env` and add your OpenAI API key to the `.env` file.

```bash
cp .env-template .env
```

## Run the server
```bash
python server.py 
```
