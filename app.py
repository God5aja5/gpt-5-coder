# app.py UPDATED TOKEN VERSION

import os
import time
import json
import sqlite3
import re
import threading
import uuid
import base64
from flask import Flask, Response, stream_with_context, request, jsonify, g, send_file
import requests
from PIL import Image
import io

# ==============================================================================
# Database Setup
# ==============================================================================
DB = "chat_history.db"
db_lock = threading.Lock()

app = Flask(__name__)

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB, timeout=10, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        try:
            db.execute("SELECT ts FROM chats LIMIT 1")
        except sqlite3.OperationalError:
            db.execute("DROP TABLE IF EXISTS chats")
            db.execute("""
            CREATE TABLE chats(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               session_id TEXT,
               role TEXT,
               message TEXT,
               ts DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
            db.commit()

def save_msg(sid, role, msg):
    with db_lock:
        db = get_db()
        db.execute("INSERT INTO chats(session_id, role, message) VALUES (?,?,?)", (sid, role, msg))
        db.commit()

def load_msgs(sid):
    db = get_db()
    cursor = db.execute("SELECT role, message FROM chats WHERE session_id=? ORDER BY ts ASC", (sid,))
    messages = []
    for row in cursor.fetchall():
        role = "assistant" if row['role'] == 'bot' else row['role']
        clean_message = re.sub(r'\\n?', '', row['message'], flags=re.IGNORECASE)
        clean_message = re.sub(r'<think>[\s\S]*?<\/think>', '', clean_message, flags=re.IGNORECASE).strip()
        if clean_message:
            messages.append({'role': role, 'content': clean_message})
    return messages

# ==============================================================================
# API Integration Section
# ==============================================================================

# --- API 1: Workik (GPT-5 Mini) with UPDATED TOKENS ---
workik_session = requests.Session()
workik_headers = {
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
    'Authorization': 'undefined',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Content-Type': 'application/json; charset=utf-8',
    'Origin': 'https://workik.com',
    'Pragma': 'no-cache',
    'Referer': 'https://workik.com/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'cross-site',
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    'X-Is-VSE': 'false',
    'X-VSE-Version': '0.0.0',
    'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
    'sec-ch-ua-mobile': '?1',
    'sec-ch-ua-platform': '"Android"',
}
workik_url = 'https://wfhbqniijcsamdp2v3i6nts4ke0ebkyj.lambda-url.us-east-1.on.aws/api_ai_playground/ai/playground/ai/trigger'

workik_base_payload = {
    "aiInput": "Hello",
    "defaultContext": [
        {
            'id': 'fd4a1e85-534f-4d73-8822-99161d46e0c7',
            'title': 'Relevant Code',
            'type': 'code',
            'description': '',
            'codeFiles': {'files': []},
            'uploadFiles': {'files': []},
            'default_add': True,
            'default_button_text': 'Add Files',
            'integrationFiles': {
                'files': [],
                'repo': {'name': '', 'id': '', 'owner': ''},
                'branch': '',
                'platform': 'github'
            }
        },
        {
            'id': '971ede3c-b26b-4b4a-a3ba-02b1b5ce0dd0',
            'title': 'Your Database Schema',
            'type': 'tables',
            'description': '',
            'tables': [],
            'databases': None,
            'schemas': None,
            'default_add': True,
            'default_button_text': 'Add Database'
        },
        {
            'id': '5e808426-8981-4482-b0de-263749ae5aa7',
            'title': 'Rest API Designs',
            'type': 'request',
            'description': '',
            'requests': [],
            'default_add': True,
            'default_button_text': 'Add APIs'
        },
        {
            'id': '749bef72-a509-49ce-8798-c573ac142725',
            'title': 'Programming Language',
            'type': 'input',
            'description': '',
            'value_text': '',
            'default_add': True,
            'default_button_text': 'Add value'
        },
        {
            'id': '15c85d87-0da2-40c1-acd0-750655e7fa5e',
            'title': 'Relevant Packages',
            'type': 'checklist',
            'description': '',
            'options_list': [],
            'seperator_text': '',
            'default_add': True,
            'default_button_text': 'Add Options'
        }
    ],
    "editScript": {
        'id': '4b10ac62-51be-4db7-a240-4f28e59aecf8',
        'name': 'My workspace',
        'messages': [{
            'type': 'question',
            'responseType': 'code',
            'sendTo': 'ai',
            'msg': 'Hello',
            'created_by': '',
            'time': '2025-08-11 00:50:42',
            'id': '1754873442623_8nsyg35ho',
            'group_id': None
        }],
        'status': 'own',
        'context': {
            'fd4a1e85-534f-4d73-8822-99161d46e0c7': {},
            '971ede3c-b26b-4b4a-a3ba-02b1b5ce0dd0': {},
            '5e808426-8981-4482-b0de-263749ae5aa7': {},
            '749bef72-a509-49ce-8798-c573ac142725': "",
            '15c85d87-0da2-40c1-acd0-750655e7fa5e': {}
        },
        'response_type': 'code',
        'created_by': ''
    },
    "all_messages": [],
    
    # --- UPDATED TOKEN VALUES ---
    "codingLanguage": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0ZXh0IjoiIFlvdSBhcmUgYW4gZXhwZXJ0IGZ1bGwtc3RhY2sgZGV2ZWxvcGVyLiBZb3Ugd2lsbCBhZGFwdCB3ZWxsIGFuZCBkZWxpdmVyIGZsYXdsZXNzIGNvZGUgaW4gYW55IGdpdmVuIHByb2dyYW1taW5nIGxhbmd1YWdlLiBQbGVhc2UgcHJvdmlkZSBkZXRhaWxlZCBjb2RlIHdpdGggcHJvcGVyIGV4cGxhbmF0aW9uLiIsImlhdCI6MTcwNTM5MDQ3M30.6n8Aj4WkaNGGcO7zXkKQtRh64vIpu7UuGAZGsDbXBq0",
    "token_type": "workik.openai:gpt_5_mini",
    "uploaded_files": {},
    "msg_type": "message",
    "wk_ld": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0eXBlIjoibG9jYWwiLCJzZXNzaW9uX2lkIjoiMTc1NTY5NDU3MSIsInJlcXVlc3RfY291bnQiOjEsImV4cCI6MTc1NjI5OTM3MX0.FCBbIjGBe-aDBUBCgVgqZYvQdKYzsZjXrU2x0b6erhc",
    "wk_ck": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0eXBlIjoiY29va2llIiwic2Vzc2lvbl9pZCI6IjE3NTU2OTQ1NzEiLCJyZXF1ZXN0X2NvdW50IjoxLCJleHAiOjE3NTYyOTkzNzF9.KS0K1kNuYpkGhR9juOXd56cyKsamnl4Z27CqGcrFfc8"
}

def clean_workik_response(text):
    """Cleans raw API response into usable text"""
    if '"content":' in text:
        try:
            clean_text = text.strip()
            if clean_text.startswith('data:'):
                clean_text = clean_text[5:].strip()
            return json.loads(clean_text)['content']
        except (json.JSONDecodeError, KeyError):
            return ''
    return ''

# --- API 2: Qween Coder ---
qween_coder_session = requests.Session()
qween_coder_headers = {
    'authority': 'promplate-api.free-chat.asia',
    'accept': '*/*',
    'accept-language': 'en-US,en;q=0.9',
    'cache-control': 'no-cache',
    'content-type': 'application/json',
    'origin': 'https://e11.free-chat.asia',
    'pragma': 'no-cache',
    'referer': 'https://e11.free-chat.asia/',
    'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
    'sec-ch-ua-mobile': '?1',
    'sec-ch-ua-platform': '"Android"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-site',
    'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
}
qween_coder_url = 'https://promplate-api.free-chat.asia/please-do-not-hack-this/single/chat_messages'

def stream_qween_coder(chat_history):
    payload = {
        'messages': chat_history,
        'model': 'qwen-3-coder-480b',
        'stream': True
    }
    try:
        with qween_coder_session.put(qween_coder_url, headers=qween_coder_headers, 
                                    json=payload, stream=True, timeout=60) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=None):
                if chunk: 
                    yield chunk.decode(errors="ignore")
    except Exception as e:
        yield f"🚨 Qwen Coder API Error: {str(e)}"

# --- API 3: Deepseek R1 Coder ---
deepseek_session = requests.Session()
deepseek_headers = {
    'Accept-Language': 'en-US,en;q=0.9',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Content-Type': 'application/json',
    'Origin': 'https://deepinfra.com',
    'Pragma': 'no-cache',
    'Referer': 'https://deepinfra.com/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    'X-Deepinfra-Source': 'web-page',
    'accept': 'text/event-stream',
    'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
    'sec-ch-ua-mobile': '?1',
    'sec-ch-ua-platform': '"Android"',
}
deepseek_url = 'https://api.deepinfra.com/v1/openai/chat/completions'

def stream_deepseek_coder(chat_history):
    system_prompt = {
        'role': 'system', 
        'content': 'You are a helpful assistant. You can write as much as the user asks, with no limit on message length.'
    }
    messages_with_prompt = [system_prompt] + chat_history
    payload = {
        'model': 'deepseek-ai/DeepSeek-R1-0528-Turbo',
        'messages': messages_with_prompt,
        'stream': True,
        'stream_options': {'include_usage': True, 'continuous_usage_stats': True},
        'max_tokens': 1000000
    }
    try:
        with deepseek_session.post(deepseek_url, headers=deepseek_headers, 
                                 json=payload, stream=True, timeout=90) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if line and line.startswith('data: '):
                    line_data = line[6:]
                    if line_data.strip() == '[DONE]': 
                        continue
                    try:
                        data = json.loads(line_data)
                        if 'choices' in data and data['choices']:
                            content = data['choices'][0].get('delta', {}).get('content', '')
                            if content: 
                                yield content
                    except json.JSONDecodeError: 
                        continue
    except Exception as e:
        yield f"🚨 Deepseek API Error: {str(e)}"

# --- API 4: Chat GPT 5 Coder ---
chat_gpt5_session = requests.Session()
chat_gpt5_cookies = {
    'ko_id': 'f1e011c8-3226-4fcb-bd73-f58945e1661b',
    'visitor-id': 'SIOtZPa7g4AVFPGFjdAyb',
    'authorization': 'Bearer%20mqeDIlwqu8hV2TsBWa96KrQu',
    'isLoggedIn': '1',
}
chat_gpt5_headers = {
    'authority': 'vercel.com',
    'accept': 'text/event-stream',
    'content-type': 'application/json',
    'origin': 'https://vercel.com',
    'referer': 'https://vercel.com/ai-gateway/models/gpt-5',
    'user-agent': 'Mozilla/5.0',
}
chat_gpt5_params = {'slug': 'babbs-projects'}
chat_gpt5_url = "https://vercel.com/api/ai/gateway-playground/chat/logged-in"

def stream_chat_gpt5_coder(chat_history):
    api_messages = []
    for msg in chat_history:
        api_messages.append({
            "parts": [{"type": "text", "text": msg['content']}],
            "id": str(uuid.uuid4()),
            "role": msg['role'],
        })
    
    payload = {
        "model": "gpt-5",
        "id": str(uuid.uuid4()),
        "messages": api_messages,
        "trigger": "submit-user-message",
    }
    
    try:
        with chat_gpt5_session.post(chat_gpt5_url, params=chat_gpt5_params, 
                                   cookies=chat_gpt5_cookies, headers=chat_gpt5_headers, 
                                   json=payload, stream=True, timeout=90) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if line and line.startswith("data:"):
                    line_data = line[5:].strip()
                    if line_data == "[DONE]": 
                        break
                    try:
                        obj = json.loads(line_data)
                        if obj.get("type") == "text-delta":
                            delta = obj.get("delta", "")
                            if not delta.startswith("__"): 
                                yield delta
                    except json.JSONDecodeError: 
                        continue
    except Exception as e:
        yield f"🚨 GPT-5 API Error: {str(e)}"

# ==============================================================================
# Flask Routes
# ==============================================================================
@app.route("/")
def index():
    return send_file('index.html')

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route("/upload_image", methods=["POST"])
def upload_image():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    try:
        image_bytes = file.read()
        image = Image.open(io.BytesIO(image_bytes))
        width, height = image.size
        file.seek(0)
        encoded_string = base64.b64encode(image_bytes).decode('utf-8')
        mime_type = file.mimetype
        base64_uri = f"data:{mime_type};base64,{encoded_string}"
        
        image_info = {
            "id": str(uuid.uuid4()),
            "name": file.filename,
            "size": len(image_bytes),
            "width": width,
            "height": height,
            "fileType": mime_type,
            "base64": base64_uri
        }
        return jsonify(image_info)
        
    except Exception as e:
        return jsonify({"error": f"Failed to process image: {str(e)}"}), 500

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json
        if not data or 'session' not in data or 'text' not in data:
            return Response("Invalid request data. 'session' and 'text' are required.", status=400)
            
        sid = data["session"]
        text = data["text"]
        model = data.get("model", "gpt-5-mini")
        image_info = data.get("imageInfo")

        user_message_to_save = f"\n{text}" if image_info else text
        save_msg(sid, "user", user_message_to_save)

        chat_history = load_msgs(sid)

        def gen():
            buffer = ""
            try:
                if model == 'qwen-coder':
                    for chunk_text in stream_qween_coder(chat_history):
                        buffer += chunk_text
                        yield chunk_text
                
                elif model == 'deepseek-coder':
                    for chunk_text in stream_deepseek_coder(chat_history):
                        buffer += chunk_text
                        yield chunk_text

                elif model == 'chat-gpt-5-coder':
                    for chunk_text in stream_chat_gpt5_coder(chat_history):
                        buffer += chunk_text
                        yield chunk_text

                else:  # Default to Workik (GPT-5 Mini) API
                    current_payload = workik_base_payload.copy()
                    current_payload["aiInput"] = text
                    current_payload["editScript"]["messages"][0]["msg"] = text
                    
                    if len(chat_history) > 1: 
                        current_payload['all_messages'] = chat_history[:-1]
                    else: 
                        current_payload['all_messages'] = []
                        
                    if image_info:
                        context_id = str(uuid.uuid4())
                        file_id = image_info['id']
                        attached_files_context = {
                            'id': context_id,
                            'title': 'Attached Files',
                            'type': 'code',
                            'codeFiles': {'files': []},
                            'uploadFiles': { 
                                'files': [{ 
                                    'id': file_id,
                                    'type': 'file',
                                    'path': '',
                                    'name': image_info['name'],
                                    'selected': False,
                                    'status': 'created',
                                    'size': image_info['size'],
                                    'height': image_info.get('height', 0),
                                    'width': image_info.get('width', 0),
                                    'fileType': image_info['fileType']
                                }]
                            },
                            'integrationFiles': { 
                                'files': [], 
                                'repo': {'name': '', 'id': '', 'owner': ''},
                                'branch': '', 
                                'platform': 'github' 
                            }
                        }
                        current_payload['defaultContext'].insert(0, attached_files_context)
                        current_payload['editScript']['context'][context_id] = {file_id: True}
                        current_payload['uploaded_files'][file_id] = image_info['base64']
                    
                    with workik_session.post(workik_url, headers=workik_headers, 
                                           json=current_payload, stream=True, timeout=60) as r:
                        r.raise_for_status() 
                        for line in r.iter_lines(decode_unicode=True):
                            if line:
                                chunk = clean_workik_response(line)
                                if chunk: 
                                    buffer += chunk
                                    yield chunk
            
            except requests.exceptions.RequestException as e:
                error_msg = f"🤖 **Connection Error**\n\nI couldn't reach the AI service for model '{model}'. Please try again later. (Details: {e})"
                yield error_msg
                buffer = error_msg
            except Exception as e:
                error_msg = f"🤖 **System Error**\n\nUnexpected error: {str(e)}"
                yield error_msg
                buffer = error_msg

            if buffer:
                with app.app_context():
                    save_msg(sid, "bot", buffer.strip())

        return Response(stream_with_context(gen()), mimetype="text/plain; charset=utf-8")
        
    except Exception as e:
        return Response(f"Server error: {str(e)}", status=500)

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
