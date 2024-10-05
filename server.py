# Based on the Twilio Media Stream Server example from OpenAI
# See https://github.com/twilio-samples/speech-assistant-openai-realtime-api-node

import asyncio
import base64
import json
import os
import subprocess
import uuid

import aiofiles
import websockets
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
    'response.function_call_arguments.done',
    'rate_limits.updated',
    'response.done',
    'input_audio_buffer.committed',
    'input_audio_buffer.speech_stopped',
    'input_audio_buffer.speech_started',
    'session.created',
    'error',
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

    # Create asyncio queue to hold audio chunks from both Twilio and OpenAI
    audio_queue = asyncio.Queue()

    # Start background task to write combined audio data to a single file asynchronously
    writer_task = asyncio.create_task(_write_audio_from_queue(audio_queue, recording_filename))

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
            'tools': [
                {
                    'name': 'get_weather',
                    'type': 'function',
                        'description': 'Determine weather in my location',
                        'parameters': {
                            'type': 'object',
                            'properties': {
                                'location': {
                                    'type': 'string',
                                    'description': 'The city and state e.g. San Francisco, CA'
                                },
                                'unit': {
                                    'type': 'string',
                                    'enum': [
                                      'c',
                                      'f'
                                    ]
                                }
                            },
                            'additionalProperties': False,
                            'required': [
                              'location',
                              'unit'
                            ]
                        }
                },
            ]
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

                        audio_append = {
                            'type': 'input_audio_buffer.append',
                            'audio': audio_payload
                        }
                        await openai_ws.send(json.dumps(audio_append))

                        await _add_to_audio_queue(audio_queue, audio_payload)
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
            await openai_ws.close()

            # Optionally, convert the recording to WAV format
            try:
                wav_filename = f'recording_{recording_id}.wav'
                conversion_command = ['ffmpeg', '-f', 'mulaw', '-ar', '8000', '-ac', '1', '-i', recording_filename, '-f', 'wav', wav_filename]
                p = subprocess.Popen(
                    conversion_command,
                    stdin=None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                p_out, p_err = p.communicate()

                if p.returncode != 0 or len(p_out) == 0:
                    raise Exception(
                        'Decoding failed. ffmpeg returned error code: {0}\n\nOutput from ffmpeg/avlib:\n\n{1}'.format(
                            p.returncode, p_err.decode(errors='ignore') 
                        )
                    )
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

                        await _add_to_audio_queue(audio_queue, audio_payload)

                    # Example of payload:
                    # {
                    #   'type': 'response.function_call_arguments.done',
                    #   'event_id': 'event_AF7Dkj55SjZfkHiNDCzSD',
                    #   'response_id': 'resp_AF7DkY3MyjvEyx9uu4Iz2',
                    #   'item_id': 'item_AF7DknCfk0nDUudzHEzBX',
                    #   'output_index': 0,
                    #   'call_id': 'call_M6sCISvlwIAiO3hG',
                    #   'name': 'get_weather',
                    #   'arguments': '{"location":"Madrid","unit":"c"}'
                    # }
                    if response['type'] == 'response.function_call_arguments.done':
                        item_id = uuid.uuid4().hex
                        tool_response = {
                            'id': item_id,
                            'call_id': response['call_id'],
                            'type': 'function_call_output',
                            'output': 'It is rainy and with 25ºC',
                        }
                        event = {
                            'event_id': item_id,
                            'type': 'conversation.item.create',
                            'item': tool_response,
                        }
                        print('\nResponding with tool response:', event)
                        await openai_ws.send(json.dumps(event))


                except Exception as e:
                    print('Error processing OpenAI message:', e, 'Raw message:', data)
        except Exception as e:
            print('Error in OpenAI WebSocket:', e)
        finally:
            await websocket.close()

    # Run both tasks concurrently
    tasks = [
        asyncio.create_task(twilio_to_openai()),
        asyncio.create_task(openai_to_twilio()),
    ]

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)

    for task in pending:
        task.cancel()

    await writer_task

    print('Client disconnected.')


# Webhook for call status updates
@app.post('/call-status')
async def call_status(request: Request):
    data = await request.body()
    print('Call Status Update:', data)
    return {'message': 'Call status received'}


# Auxiliary functions ---------------------------------------------------------

async def _add_to_audio_queue(audio_queue, audio_payload):
    """Queue audio data for writing to a file asynchronously"""
    decoded_audio = base64.b64decode(audio_payload)
    await audio_queue.put(decoded_audio)


async def _write_audio_from_queue(queue, filename):
    """Helper function to write audio data from a queue"""
    async with aiofiles.open(filename, mode='wb') as audio_file:
        while True:
            audio_chunk = await queue.get()
            if audio_chunk is None:
                break
            # Write combined audio to the file asynchronously
            await audio_file.write(audio_chunk)


# Run the app
if __name__ == '__main__':
    import uvicorn
    uvicorn.run('server:app', host='0.0.0.0', port=PORT)
