# Based on the Twilio Media Stream Server example from OpenAI
# See https://github.com/twilio-samples/speech-assistant-openai-realtime-api-node

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
import os
import asyncio
import websockets
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

if not OPENAI_API_KEY:
    print('Missing OpenAI API key. Please set it in the .env file.')
    exit(1)

# Initialize FastAPI
app = FastAPI()

# Constants
SYSTEM_MESSAGE = ('You are a helpful and bubbly AI assistant who loves to chat about anything the user is '
                  'interested about and is prepared to offer them facts. You have a penchant for dad jokes, '
                  'owl jokes, and rickrolling – subtly. Always stay positive, but work in a joke when appropriate.')
VOICE = 'alloy'
PORT = int(os.getenv('PORT', 5050))  # Allow dynamic port assignment

# List of Event Types to log to the console
LOG_EVENT_TYPES = [
    'response.content.done',
    'rate_limits.updated',
    'response.done',
    'input_audio_buffer.committed',
    'input_audio_buffer.speech_stopped',
    'input_audio_buffer.speech_started',
    'session.created'
]

# Root Route
@app.get('/')
async def root():
    return {'message': 'Twilio Media Stream Server is running!'}

# Route for Twilio to handle incoming and outgoing calls
@app.api_route('/incoming-call', methods=['GET', 'POST'])
async def incoming_call(request: Request):
    host = request.headers.get('host')
    twiml_response = f'''<?xml version='1.0' encoding='UTF-8'?>
<Response>
    <Say>Please wait while we connect your call to the A. I. voice assistant, powered by Twilio and the Open-A.I. Realtime API</Say>
    <Pause length='1'/>
    <Say>O.K. you can start talking!</Say>
    <Connect>
        <Stream url='wss://{host}/media-stream' />
    </Connect>
</Response>'''
    return PlainTextResponse(content=twiml_response, media_type='text/xml')

# WebSocket route for media-stream
@app.websocket('/media-stream')
async def media_stream(websocket: WebSocket):
    print('Client connected')
    await websocket.accept()

    # Connect to OpenAI Realtime API
    openai_ws = await websockets.connect(
        'wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01',
        extra_headers={
            'Authorization': f'Bearer {OPENAI_API_KEY}',
            'OpenAI-Beta': 'realtime=v1'
        }
    )

    # Send session update after connection stability
    await asyncio.sleep(0.25)
    session_update = {
        'type': 'session.update',
        'session': {
            'turn_detection': {'type': 'server_vad'},
            'input_audio_format': 'g711_ulaw',
            'output_audio_format': 'g711_ulaw',
            'voice': VOICE,
            'instructions': SYSTEM_MESSAGE,
            'modalities': ['text', 'audio'],
            'temperature': 0.8,
        }
    }
    print('Sending session update:', json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))

    stream_sid = None

    # Handle incoming messages from Twilio
    async def twilio_to_openai():
        nonlocal stream_sid
        try:
            while True:
                message = await websocket.receive_text()
                data = json.loads(message)
                event = data.get('event')

                if event == 'media':
                    if openai_ws.open:
                        audio_append = {
                            'type': 'input_audio_buffer.append',
                            'audio': data['media']['payload']
                        }
                        await openai_ws.send(json.dumps(audio_append))
                elif event == 'start':
                    stream_sid = data['start']['streamSid']
                    print('Incoming stream has started', stream_sid)
                else:
                    print('Received non-media event:', event)
        except WebSocketDisconnect:
            print('WebSocket disconnected from Twilio')
        except Exception as e:
            print('Error parsing message:', e)
        finally:
            await openai_ws.close()

    # Listen for messages from the OpenAI WebSocket
    async def openai_to_twilio():
        try:
            async for data in openai_ws:
                try:
                    response = json.loads(data)

                    if response['type'] in LOG_EVENT_TYPES:
                        print(f'Received event: {response["type"]}', response)

                    if response['type'] == 'session.updated':
                        print('Session updated successfully:', response)

                    if response['type'] == 'response.audio.delta' and 'delta' in response:
                        audio_delta = {
                            'event': 'media',
                            'streamSid': stream_sid,
                            'media': {'payload': response['delta']}
                        }
                        await websocket.send_text(json.dumps(audio_delta))
                except Exception as e:
                    print('Error processing OpenAI message:', e, 'Raw message:', data)
        except Exception as e:
            print('Error in OpenAI WebSocket:', e)
        finally:
            await websocket.close()

    # Run both tasks concurrently
    tasks = [
        asyncio.create_task(twilio_to_openai()),
        asyncio.create_task(openai_to_twilio())
    ]

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)

    for task in pending:
        task.cancel()

    print('Client disconnected.')

# Run the app
if __name__ == '__main__':
    import uvicorn
    uvicorn.run('server:app', host='0.0.0.0', port=PORT)
