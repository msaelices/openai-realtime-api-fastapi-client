# openai-realtime-api-fastapi-client

## Installation

Dependencies:
- Python
- ffmpeg with mulaw codec

### Ubuntu
Install the dependencies:
```bash
sudo apt-get install python3 python3-venv
sudo apt-get install ffmpeg
sudo apt-get install libavcodec-extra
```

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
