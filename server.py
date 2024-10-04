# Based on the Twilio Media Stream Server example from OpenAI
# See https://github.com/twilio-samples/speech-assistant-openai-realtime-api-node

import base64
import os
import asyncio
import websockets
import json
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

# Load environment variables from .env file
load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

if not OPENAI_API_KEY:
    print('Missing OpenAI API key. Please set it in the .env file.')
    exit(1)

# Initialize FastAPI
app = FastAPI()

# Constants
INSTRUCTIONS = os.getenv('INSTRUCTIONS')

VOICE = os.getenv('VOICE', 'alloy')
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
    form = await request.form()
    print('Incoming Call:', form)
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

    # Generate a unique identifier for the recording
    recording_id = str(uuid.uuid4())
    recording_filename = f'recording_{recording_id}.ulaw'

    # Open the file in binary write mode
    audio_file = open(recording_filename, 'wb')

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
            'instructions': INSTRUCTIONS,
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
                        audio_payload = data['media']['payload']

                        # Decode the base64-encoded audio and write it to the file
                        decoded_audio = base64.b64decode(audio_payload)
                        audio_file.write(decoded_audio)

                        audio_append = {
                            'type': 'input_audio_buffer.append',
                            'audio': audio_payload
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
            # Close the audio file when done
            audio_file.close()
            await openai_ws.close()

            # Optionally, convert the recording to WAV format
            try:
                from pydub import AudioSegment
                audio = AudioSegment.from_file(
                    recording_filename,
                    codec='mulaw',
                    sample_width=2,
                    frame_rate=8000,
                    channels=1,
                )
                wav_filename = f'recording_{recording_id}.wav'
                audio.export(wav_filename, format='wav')
                print(f'Recording saved as {wav_filename}')
                # Optionally, delete the .ulaw file
                os.remove(recording_filename)
            except Exception as e:
                print('Error converting recording to WAV:', e)

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
                        audio_payload = response['delta']

                        audio_delta = {
                            'event': 'media',
                            'streamSid': stream_sid,
                            'media': {'payload': audio_payload}
                        }
                        await websocket.send_text(json.dumps(audio_delta))

                        # Decode the base64-encoded audio and write it to the file
                        decoded_audio = base64.b64decode(audio_payload)
                        audio_file.write(decoded_audio)
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


# Webhook for call status updates
@app.post('/call-status')
async def call_status(request: Request):
    data = await request.body()
    print('Call Status Update:', data)
    return {'message': 'Call status received'}


# Run the app
if __name__ == '__main__':
    import uvicorn
    uvicorn.run('server:app', host='0.0.0.0', port=PORT)
