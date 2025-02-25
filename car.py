from guardrails_simlab_client import simlab_connect
from guardrails_simlab_client.processors.test_processor import test_context
from litellm import litellm
import requests
import websockets
import json
import asyncio
import time
import uuid
import logging
from typing import Dict, Tuple, Optional, Any
from dataclasses import dataclass
from websockets.client import WebSocketClientProtocol
from guardrails_simlab_client.env import _get_api_key, _get_app_id

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class WebSocketConnection:
    websocket: WebSocketClientProtocol
    token: str
    last_activity: float

class WebSocketManager:
    def __init__(self, max_connections: int = 4, timeout_minutes: int = 5):
        self.max_connections = max_connections
        self.timeout_minutes = timeout_minutes
        self.active_connections: Dict[str, WebSocketConnection] = {}
        self.pending_queue = asyncio.Queue()
        
    async def get_leaf_nodes(self, experiment_id: str) -> list:
        """Fetch conversation leaf nodes for an experiment"""
        url = f'https://dev.api.simlab.guardrailsai.com/client/experiments/{experiment_id}/conversation-leafs'
        headers = {
            'x-api-key': _get_api_key(),
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

    async def create_websocket_connection(self, token: str) -> WebSocketClientProtocol:
        """Create a new websocket connection"""
        uri = f'wss://webchat-api.pulsar.ai/wss?access_token={token}'
        logger.info(f"Creating websocket connection to {uri}")
        websocket = await websockets.connect(
            uri,
            additional_headers={
                'Origin': 'https://www.arlingtonnissan.com',
                'Cache-Control': 'no-cache',
                'Accept-Language': 'en-US,en;q=0.6',
                'Pragma': 'no-cache'
            }
        )
        
        # Send ChatOpen event when establishing new connection
        chat_open_data = {
            "event_name": "ChatOpen",
            "id": str(uuid.uuid4()),
            "page": "vdp"
        }
        logger.info(f"Sending ChatOpen event: {chat_open_data}")
        await websocket.send(json.dumps(chat_open_data))
        
        return websocket

    def cleanup_inactive_connections(self):
        """Close and remove connections that have timed out"""
        current_time = time.time()
        timeout = self.timeout_minutes * 60
        
        for root_id in list(self.active_connections.keys()):
            conn = self.active_connections[root_id]
            if current_time - conn.last_activity > timeout:
                asyncio.create_task(conn.websocket.close())
                del self.active_connections[root_id]

    async def get_or_create_connection(self, root_id: str) -> Tuple[WebSocketClientProtocol, str]:
        """Get existing connection or create new one if slots available"""
        # Check if connection exists and is still valid
        if root_id in self.active_connections:
            conn = self.active_connections[root_id]
            conn.last_activity = time.time()
            return conn.websocket, conn.token
            
        # Clean up timed out connections
        self.cleanup_inactive_connections()
        
        # If at max connections, queue the request
        if len(self.active_connections) >= self.max_connections:
            await self.pending_queue.put(root_id)
            # Wait for slot to become available
            while len(self.active_connections) >= self.max_connections:
                await asyncio.sleep(1)
                self.cleanup_inactive_connections()
                
        # Create new connection
        auth_response = authorize_pulsar()
        token = auth_response['access_token']
        websocket = await self.create_websocket_connection(token)
        
        self.active_connections[root_id] = WebSocketConnection(
            websocket=websocket,
            token=token,
            last_activity=time.time()
        )
        
        return websocket, token

    async def send_message(self, websocket: WebSocketClientProtocol, message: str) -> str:
        """Send a message through websocket and get response"""
        logger.info(f"Sending message: {message[:100]}...")
        message_data = {
            "event_name": "Message",
            "id": str(uuid.uuid4()),
            "page": "vdp",
            "payload": message
        }
        logger.info(f"Sending message data: {message_data}")
        await websocket.send(json.dumps(message_data))
        
        # Wait for acknowledgment
        ack_response = await websocket.recv()
        ack_data = json.loads(ack_response)
        logger.info(f"Received ack: {str(ack_data)[:200]}...")
        
        # Wait for actual bot response
        while True:
            logger.info("Waiting for response...")
            response = await websocket.recv()
            response_data = json.loads(response)
            logger.info(f"Raw websocket response: {str(response_data)[:200]}...")
            
            if response_data.get('event_name') == 'Message' and response_data.get('initiator') == 'BOT':
                if isinstance(response_data.get('message'), dict):
                    response_text = response_data['message'].get('text')
                    if response_text:
                        logger.info(f"Extracted BOT response text: {response_text[:100]}...")
                        return response_text
                    
            await asyncio.sleep(1)
            
            # # If we get another ack or unrecognized format, keep waiting
            # if response_data.get('event_name') == 'ack':

            #     continue
                
            logger.warning(f"Unexpected response format: {response[:200]}...")

def authorize_pulsar() -> dict:
    """
    Authorize with the Pulsar API using the provided user ID.
    """
    user_id = str(uuid.uuid4())
    url = 'https://webchat-api.pulsar.ai/api/v1/auth/authorize'
    headers = {
        'accept': '*/*',
        'content-type': 'application/json',
        'x-api-key': 'gAAAAABmWZY8Z6fMZyZRUW651SwpJuJqhxFPmW3L2Lrnwfr4ek-BkTTpnJq2WFYTyrSDLzPXAAizn6QjeWUOK3Zrtqh6-WJRrM1h89zit2JTBUZYXjzMmtY=',
        'origin': 'https://www.arlingtonnissan.com',
        'referer': 'https://www.arlingtonnissan.com/'
    }
    data = {'user_id': user_id}
    
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()  # Raises an exception for bad status codes
    return response.json()

# Create a global WebSocketManager instance
ws_manager = WebSocketManager()

@simlab_connect(
    enable=True,
    control_plane_host="https://dev.api.simlab.guardrailsai.com",
    application_id="0bd50539-23ae-48a6-909e-14c908efcb4c",
    throttle_time=0,
    max_workers=5
)
def my_application_interface(messages: list[dict[str, str]]) -> str:
    context = test_context.get()
    
    if context and context.get('experiment_id'):
        async def process_message():
            try:
                # Get auth token for simlab API
                auth_response = authorize_pulsar()
                auth_token = auth_response['access_token']
                
                # Get leaf nodes to find root_id
                leaf_nodes = await ws_manager.get_leaf_nodes(context['experiment_id'])
                
                # Find matching leaf node and get root_id
                root_id = None
                for node in leaf_nodes:
                    if node['id'] == context['test_id']:
                        root_id = node['root_id']
                        break
                        
                if root_id:
                    # Get or create websocket connection
                    websocket, _ = await ws_manager.get_or_create_connection(root_id)
                    
                    # Send message through websocket
                    return await ws_manager.send_message(websocket, messages[-1]['content'])
                    
            except Exception as e:
                print(f"Error in websocket processing: {e}")
                # Fallback to regular LLM if websocket fails
                res = litellm.completion(
                    model="gpt-4o-mini",
                    messages=messages
                )
                return res.choices[0].message.content
                
        return asyncio.run(process_message())
    
    # Regular LLM processing when no context
    res = litellm.completion(
        model="gpt-4o-mini",
        messages=messages
    )
    return res.choices[0].message.content


if __name__ == '__main__':
    print("Running example.py")
    prompt = "It was the best of times, it was the worst of times."
    out = my_application_interface([{
        "role": "user", 
        "content": prompt
    }])
    print(out)
