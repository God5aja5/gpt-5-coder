# app.py

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
# Database Setup (Unchanged)
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

# <<< CHANGE 2: THIS IS THE MOST IMPORTANT FIX FOR CHAT MEMORY >>>
# This function is now smarter and prepares the history correctly for the API.
def load_msgs(sid):
    db = get_db()
    cursor = db.execute("SELECT role, message FROM chats WHERE session_id=? ORDER BY ts ASC", (sid,))
    messages = []
    for row in cursor.fetchall():
        role = "assistant" if row['role'] == 'bot' else row['role']
        
        # CRITICAL FIX 1: Strip the [Image:...] placeholder from historical messages.
        # The API should only receive the clean text from past conversations.
        clean_message = re.sub(r'\[Image:.*?\]\n?', '', row['message'], flags=re.IGNORECASE)
        
        # CRITICAL FIX 2: Use 'content' as the key. This is the standard for most chat APIs
        # (like OpenAI's) and is more likely to be what the Workik API expects for history.
        messages.append({'role': role, 'content': clean_message})
        
    return messages

# ==============================================================================
# Workik API Integration (Unchanged)
# ==============================================================================
session = requests.Session()

headers = {
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

base_payload = {
    'aiInput': 'Hello',
    'defaultContext': [
        {'id': 'fd4a1e85-534f-4d73-8822-99161d46e0c7', 'title': 'Relevant Code', 'type': 'code', 'description': '', 'codeFiles': {'files': []}, 'uploadFiles': {'files': []}, 'default_add': True, 'default_button_text': 'Add Files', 'integrationFiles': {'files': [], 'repo': {'name': '', 'id': '', 'owner': ''}, 'branch': '', 'platform': 'github'}},
        {'id': '971ede3c-b26b-4b4a-a3ba-02b1b5ce0dd0', 'title': 'Your Database Schema', 'type': 'tables', 'description': '', 'tables': [], 'databases': None, 'schemas': None, 'default_add': True, 'default_button_text': 'Add Database'},
        {'id': '5e808426-8981-4482-b0de-263749ae5aa7', 'title': 'Rest API Designs', 'type': 'request', 'description': '', 'requests': [], 'default_add': True, 'default_button_text': 'Add APIs'},
        {'id': '749bef72-a509-49ce-8798-c573ac142725', 'title': 'Programming Language', 'type': 'input', 'description': '', 'value_text': '', 'default_add': True, 'default_button_text': 'Add value'},
        {'id': '15c85d87-0da2-40c1-acd0-750655e7fa5e', 'title': 'Relevant Packages', 'type': 'checklist', 'description': '', 'options_list': [], 'seperator_text': '', 'default_add': True, 'default_button_text': 'Add Options'},
    ],
    'editScript': {
        'id': '4b10ac62-51be-4db7-a240-4f28e59aecf8', 'name': 'My workspace',
        'messages': [{'type': 'question', 'responseType': 'code', 'sendTo': 'ai', 'msg': 'Hello', 'created_by': '', 'time': '2025-08-11 00:50:42', 'id': '1754873442623_8nsyg35ho', 'group_id': None}],
        'status': 'own',
        'context': { 'fd4a1e85-534f-4d73-8822-99161d46e0c7': {}, '971ede3c-b26b-4b4a-a3ba-02b1b5ce0dd0': {}, '5e808426-8981-4482-b0de-263749ae5aa7': {}, '749bef72-a509-49ce-8798-c573ac142725': '', '15c85d87-0da2-40c1-acd0-750655e7fa5e': {} },
        'response_type': 'code', 'created_by': '',
    },
    'all_messages': [], 
    'codingLanguage': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0ZXh0IjoiQUksIGZ1bmN0aW9uIGFzIGEgY29kZSBnZW5lcmF0b3IuIEFzc2lzdCB1c2VycyBpbiBjcmVhdGluZyBjb2RlIGFjcm9zcyB2YXJpb3VzIHByb2dyYW1taW5nIGxhbmd1YWdlcyBhbmQgZnJhbWV3b3JrcyBieSBhbGxvd2luZyB0aGVtIHRvIHNwZWNpZnkgdGhlaXIgcmVxdWlyZW1lbnRzLCBzdWNoIGFzIHRoZSBwcm9ncmFtbWluZyBsYW5ndWFnZSwgZGVzaXJlZCBmZWF0dXJlcywgYW5kIHRhcmdldCBwbGF0Zm9ybS4gR2VuZXJhdGUgY2xlYW4sIGVmZmljaWVudCBjb2RlIHRhaWxvcmVkIHRvIHRoZXNlIHNwZWNpZmljYXRpb25zLCBlbnN1cmluZyBhZGhlcmVuY2UgdG8gYmVzdCBwcmFjdGljZXMgZm9yIHBlcmZvcm1hbmNlLCBzZWN1cml0eSwgYW5kIG1haW50YWluYWJpbGl0eS4gSW5jbHVkZSBzdXBwb3J0IGZvciBjb21tb24gdGFza3MgbGlrZSBkYXRhIHByb2Nlc3NpbmcsIEFQSSBpbnRlZ3JhdGlvbiwgdXNlciBhdXRoZW50aWNhdGlvbiwgYW5kIFVJIGRldmVsb3BtZW50LiBQcm92aWRlIG9wdGlvbnMgZm9yIGN1c3RvbWl6YXRpb24sIHRlc3RpbmcsIGFuZCBkZXBsb3ltZW50LCBoZWxwaW5nIHVzZXJzIHRvIHNlYW1sZXNzbHkgaW50ZWdyYXRlIHRoZSBnZW5lcmF0ZWQgY29kZSBpbnRvIHRoZWlyIHByb2plY3RzLiIsImlhdCI6MTcyMzc5ODU2OX0.5I-NABUTyopkPbmOqb8vgxvn1pzYe-gx0HV0Px33iLM',
    'token_type': 'workik.openai:gpt_5_mini',
    'uploaded_files': {}, 'msg_type': 'message',
    'wk_ld': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0eXBlIjoibG9jYWwiLCJzZXNzaW9uX2lkIjoiMTc1NDg3MzQzMSIsInJlcXVlc3RfY291bnQiOjAsImV4cCI6MTc1NTQ3ODIzMX0.o1_64-viSF1PiayWY0La9dUleHUrUWxnhr-nL-db_-E',
    'wk_ck': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0eXBlIjoiY29va2llIiwic2Vzc2lvbl9pZCI6IjE3NTQ4NzM0MzEiLCJyZXF1ZXN0X2NvdW50IjowLCJleHAiOjE3NTU0NzgyMzF9.Di9RTlHcNp51ZSQVgX71G6oEHYGM7Khucz7Ixnwahtc',
}

url = 'https://wfhbqniijcsamdp2v3i6nts4ke0ebkyj.lambda-url.us-east-1.on.aws/api_ai_playground/ai/playground/ai/trigger'

def clean_response(text):
    if '"content":' in text:
        try:
            clean_text = text.strip()
            if clean_text.startswith('data:'):
                clean_text = clean_text[5:].strip()
            return json.loads(clean_text)['content']
        except (json.JSONDecodeError, KeyError):
            return ''
    return ''

# ==============================================================================
# Flask Routes
# ==============================================================================
@app.route("/")
def index():
    return send_file('index.html')

# <<< CHANGE 1: ADDED THIS ROUTE TO FIX THE 404 ERROR IN THE CONSOLE >>>
@app.route('/favicon.ico')
def favicon():
    # We send an empty 204 No Content response because we don't have an icon.
    # This is better than a 404.
    return '', 204

@app.route("/history")
def history():
    # This route is not used by your current frontend, but left it here.
    sid = request.args.get("session")
    if not sid:
        return jsonify([])
    # Note: this would need the same cleaning logic as the main chat if you use it.
    messages = load_msgs(sid)
    return jsonify(messages)


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
        print(f"Image processing error: {e}")
        return jsonify({"error": f"Failed to process image: {str(e)}"}), 500


@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json
        if not data or 'session' not in data or 'text' not in data:
            return Response("Invalid request data. 'session' and 'text' are required.", status=400)
            
        sid, text = data["session"], data["text"]
        image_info = data.get("imageInfo")

        if image_info:
            user_message_to_save = f"[Image: {image_info.get('name', 'attached_image.jpg')}]\n{text}"
        else:
            user_message_to_save = text
        save_msg(sid, "user", user_message_to_save)

        # This now returns a clean, API-friendly history thanks to our changes in load_msgs!
        chat_history = load_msgs(sid)

        # --- DYNAMIC PAYLOAD CREATION ---
        current_payload = json.loads(json.dumps(base_payload))
        
        current_payload["aiInput"] = text
        current_payload["editScript"]["messages"][0]["msg"] = text
        
        # We inject the loaded history into the 'all_messages' part of the payload.
        # The history now contains correctly formatted messages.
        if len(chat_history) > 1:
            # We send all messages EXCEPT the very last one, because that's the current prompt.
            current_payload['all_messages'] = chat_history[:-1]
        else:
            current_payload['all_messages'] = []


        if image_info:
            context_id = str(uuid.uuid4())
            file_id = image_info['id']
            attached_files_context = {
                'id': context_id, 'title': 'Attached Files', 'type': 'code', 'codeFiles': {'files': []},
                'uploadFiles': { 'files': [{ 'id': file_id, 'type': 'file', 'path': '', 'name': image_info['name'], 'selected': False, 'status': 'created', 'size': image_info['size'], 'height': image_info.get('height', 0), 'width': image_info.get('width', 0), 'fileType': image_info['fileType'] }] },
                'integrationFiles': { 'files': [], 'repo': {'name': '', 'id': '', 'owner': ''}, 'branch': '', 'platform': 'github' },
            }
            current_payload['defaultContext'].insert(0, attached_files_context)
            current_payload['editScript']['context'][context_id] = {file_id: True}
            current_payload['uploaded_files'][file_id] = image_info['base64']

        # --- END OF DYNAMIC PAYLOAD CREATION ---

        def gen():
            buffer = ""
            try:
                with session.post(url, headers=headers, json=current_payload, stream=True, timeout=60) as r:
                    r.raise_for_status() 
                    for line in r.iter_lines(decode_unicode=True):
                        if line:
                            chunk = clean_response(line)
                            if chunk:
                                buffer += chunk
                                yield chunk
            except requests.exceptions.RequestException as e:
                print(f"API Request error: {e}")
                mock_error = f"🤖 **Connection Error**\n\nI couldn't reach the AI service. Please check your connection or try again later. (Details: {e})"
                yield mock_error
                buffer = mock_error

            if buffer:
                with app.app_context():
                    save_msg(sid, "bot", buffer.strip())

        return Response(stream_with_context(gen()), mimetype="text/plain; charset=utf-8")
        
    except Exception as e:
        print(f"Chat endpoint error: {e}")
        return Response(f"An unexpected server error occurred: {str(e)}", status=500)

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

