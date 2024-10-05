# Twilio and OpenAI Realtime API integration with FastAPI

This repo demonstrates how to use FastAPI, [Twilio](https://www.twilio.com/), and [OpenAI's Realtime API](https://platform.openai.com/docs/) to make a phone call to speak with an AI Assistant. 

The application opens websockets with the OpenAI Realtime API and Twilio, and sends voice audio from one to the other to enable a two-way conversation.

Based on this Twilio NodeJS based sample code: https://github.com/twilio-samples/speech-assistant-openai-realtime-api-node/

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

## Usage

1. Login in the Twilio console and buy a phone number.

2. Configure the phone number to use the webhook URLs of your FastAPI server:
  - A Call Comes In -> Webhook -> http://your-server-url/incoming-call
  - Call Status Changes -> Webhook -> http://your-server-url/call-status

    Note: You can use tools like ngrok to expose your local server to the internet.

3. Call the phone number and speak with the AI Assistant.
