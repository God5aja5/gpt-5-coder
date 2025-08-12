import os
import time
import json
import sqlite3
import re
import threading
from flask import Flask, Response, stream_with_context, request, jsonify, g, send_file
import requests
import base64 
import mimetypes 

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

# ### FIX 1: SIMPLIFIED AND ROBUST MESSAGE SAVING AND LOADING ###
# This ensures that ALL messages for Qwen are handled as JSON strings in the database.
def save_msg(sid, role, msg_content):
    with db_lock:
        db = get_db()
        # For Qwen, msg_content is always a list of dicts. We convert it to a JSON string.
        # For Workik, it's a plain string.
        message_to_save = json.dumps(msg_content) if isinstance(msg_content, list) else msg_content
        db.execute(
            "INSERT INTO chats(session_id, role, message) VALUES (?,?,?)",
            (sid, role, message_to_save)
        )
        db.commit()

def load_msgs(sid, model_name='workik'):
    db = get_db()
    cursor = db.execute("SELECT role, message FROM chats WHERE session_id=? ORDER BY ts ASC", (sid,))
    messages = []
    for row in cursor.fetchall():
        role = row['role']
        message_content = row['message']
        
        if model_name == 'qwen':
            # For Qwen, we expect the message in the DB to be a JSON string
            # representing the list of content parts.
            try:
                content_list = json.loads(message_content)
                messages.append({'role': role, 'content': content_list})
            except (json.JSONDecodeError, TypeError):
                # Fallback: if we find an old, plain-text message in the DB,
                # we wrap it in the required structure to avoid API errors.
                messages.append({'role': role, 'content': [{'type': 'text', 'text': str(message_content)}]})
        else: # Original behavior for workik
             messages.append({'role': 'user' if role == 'user' else 'assistant', 'content': message_content})

    return messages

# ==============================================================================
# Workik API Integration (Unchanged)
# ==============================================================================
workik_session = requests.Session()
workik_headers = {
    'Accept': 'application/json', 'Accept-Language': 'en-US,en;q=0.9', 'Authorization': 'undefined',
    'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'Content-Type': 'application/json; charset=utf-8',
    'Origin': 'https://workik.com', 'Pragma': 'no-cache', 'Referer': 'https://workik.com/',
    'Sec-Fetch-Dest': 'empty', 'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Site': 'cross-site',
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    'X-Is-VSE': 'false', 'X-VSE-Version': '0.0.0', 'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
    'sec-ch-ua-mobile': '?1', 'sec-ch-ua-platform': '"Android"',
}
workik_payload_template = {
    'aiInput': '','defaultContext': [{'id': 'fd4a1e85-534f-4d73-8822-99161d46e0c7','title': 'Relevant Code','type': 'code','description': '','codeFiles': {'files': []},'uploadFiles': {'files': []},'default_add': True,'default_button_text': 'Add Files','integrationFiles': {'files': [],'repo': {'name': '','id': '','owner': ''},'branch': '','platform': 'github',},},{'id': '971ede3c-b26b-4b4a-a3ba-02b1b5ce0dd0','title': 'Your Database Schema','type': 'tables','description': '','tables': [],'databases': None,'schemas': None,'default_add': True,'default_button_text': 'Add Database',},{'id': '5e808426-8981-4482-b0de-263749ae5aa7','title': 'Rest API Designs','type': 'request','description': '','requests': [],'default_add': True,'default_button_text': 'Add APIs',},{'id': '749bef72-a509-49ce-8798-c573ac142725','title': 'Programming Language','type': 'input','description': '','value_text': '','default_add': True,'default_button_text': 'Add value',},{'id': '15c85d87-0da2-40c1-acd0-750655e7fa5e','title': 'Relevant Packages','type': 'checklist','description': '','options_list': [],'seperator_text': '','default_add': True,'default_button_text': 'Add Options',},],'editScript': {'id': '4b10ac62-51be-4db7-a240-4f28e59aecf8','name': 'My workspace','messages': [{'type': 'question','responseType': 'code','sendTo': 'ai','msg': '','created_by': '','time': '2025-08-11 00:50:42','id': '1754873442623_8nsyg35ho','group_id': None,}],'status': 'own','context': {'fd4a1e85-534f-4d73-8822-99161d46e0c7': {},'971ede3c-b26b-4b4a-a3ba-02b1b5ce0dd0': {},'5e808426-8981-4482-b0de-263749ae5aa7': {},'749bef72-a509-49ce-8798-c573ac142725': '','15c85d87-0da2-40c1-acd0-750655e7fa5e': {},},'response_type': 'code','created_by': '',},'all_messages': [],'codingLanguage': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0ZXh0IjoiQUksIGZ1bmN0aW9uIGFzIGEgY29kZSBnZW5lcmF0b3IuIEFzc2lzdCB1c2VycyBpbiBjcmVhdGluZyBjb2RlIGFjcm9zcyB2YXJpb3VzIHByb2dyYW1taW5nIGxhbmd1YWdlcyBhbmQgZnJhbWV3b3JrcyBieSBhbGxvd2luZyB0aGVtIHRvIHNwZWNpZnkgdGhlaXIgcmVxdWlyZW1lbnRzLCBzdWNoIGFzIHRoZSBwcm9ncmFtbWluZyBsYW5ndWFnZSwgZGVzaXJlZCBmZWF0dXJlcywgYW5kIHRhcmdldCBwbGF0Zm9ybS4gR2VuZXJhdGUgY2xlYW4sIGVmZmljaWVudCBjb2RlIHRhaWxvcmVkIHRvIHRoZXNlIHNwZWNpZmljYXRpb25zLCBlbnN1cmluZyBhZGhlcmVuY2UgdG8gYmVzdCBwcmFjdGljZXMgZm9yIHBlcmZvcm1hbmNlLCBzZWN1cml0eSwgYW5kIG1haW50YWluYWJpbGl0eS4gSW5jbHVkZSBzdXBwb3J0IGZvciBjb21tb24gdGFza3MgbGlrZSBkYXRhIHByb2Nlc3NpbmcsIEFQSSBpbnRlZ3JhdGlvbiwgdXNlciBhdXRoZW50aWNhdGlvbiwgYW5kIFVJIGRldmVsb3BtZW50LiBQcm92aWRlIG9wdGlvbnMgZm9yIGN1c3RvbWl6YXRpb24sIHRlc3RpbmcsIGFuZCBkZXBsb3ltZW50LCBoZWxwaW5nIHVzZXJzIHRvIHNlYW1sZXNzbHkgaW50ZWdyYXRlIHRoZSBnZW5lcmF0ZWQgY29kZSBpbnRvIHRoZWlyIHByb2plY3RzLiIsImlhdCI6MTcyMzc5ODU2OX0.5I-NABUTyopkPbmOqb8vgxvn1pzYe-gx0HV0Px33iLM','token_type': 'workik.openai:gpt_5_mini','uploaded_files': {},'msg_type': 'message','wk_ld': 'eyJhbGciOiJIOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0eXBlIjoibG9jYWwiLCJzZXNzaW9uX2lkIjoiMTc1NDg3MzQzMSIsInJlcXVlc3RfY291bnQiOjAsImV4cCI6MTc1NTQ3ODIzMX0.o1_64-viSF1PiayWY0La9dUleHUrUWxnhr-nL-db_-E','wk_ck': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0eXBlIjoiY29va2llIiwic2Vzc2lvbl9pZCI6IjE3NTQ4NzM0MzEiLCJyZXF1ZXN0X2NvdW50IjowLCJleHAiOjE3NTU0NzgyMzF9.Di9RTlHcNp51ZSQVgX71G6oEHYGM7Khucz7Ixnwahtc',
}
workik_url = 'https://wfhbqniijcsamdp2v3i6nts4ke0ebkyj.lambda-url.us-east-1.on.aws/api_ai_playground/ai/playground/ai/trigger'

def clean_workik_response(text):
    if '"content":' in text:
        try:
            clean_text = text.strip()
            if clean_text.startswith('data:'): clean_text = clean_text[5:].strip()
            return json.loads(clean_text)['content']
        except (json.JSONDecodeError, KeyError): return ''
    return ''

# ==============================================================================
# Qwen Max 2.5 API Integration (CORRECTED SECTION)
# ==============================================================================
qwen_session = requests.Session()
QWEN_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# ### FIX 2: UPDATED HEADERS TO MATCH WORKING EXAMPLE ###
# This ensures we are sending what OpenRouter expects from a browser/app client.
QWEN_HEADERS = {
    'Authorization': 'Bearer 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',
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    # It's good practice for these to match your frontend's origin/referer if you have one.
    # We take these from the working example as they are known to be accepted.
    'Referer': 'https://seraai.vercel.app/', 
    'Origin': 'https://seraai.vercel.app',
    'X-Title': 'Mini GPT Pro' # Or your app's name
}

QWEN_MODEL = "qwen/qwen2.5-vl-72b-instruct:free"
MAX_HISTORY = 20

def get_qwen_response_stream(sid, text, image_data_url):
    """Generator function to stream responses from the Qwen API."""
    # Load history, which will be correctly formatted by our new `load_msgs`
    history = load_msgs(sid, model_name='qwen')

    # Construct the `content` list for the new user message.
    new_user_content = []
    if text:
        new_user_content.append({"type": "text", "text": text})
    if image_data_url:
        new_user_content.append({"type": "image_url", "image_url": {"url": image_data_url}})

    # Only proceed if there is actual content to send
    if not new_user_content:
        yield "Please provide text or an image."
        return

    # Save the new user message (as a structured list) and add to current history
    save_msg(sid, "user", new_user_content)
    history.append({"role": "user", "content": new_user_content})

    # Trim history
    if len(history) > MAX_HISTORY:
        # Keep the system prompt + the last N messages
        history = history[-MAX_HISTORY:]

    # ### FIX 3: ADDING A SYSTEM PROMPT ###
    # Just like the working example, a system prompt is crucial for setting context.
    # It should be at the beginning of the messages array.
    messages_for_api = [
        {"role": "system", "content": [{"type": "text", "text": "You are a helpful AI assistant."}]}
    ] + history
    
    qwen_payload = {"model": QWEN_MODEL, "messages": messages_for_api, "stream": True}
    
    full_reply = ""
    try:
        # Using a `with` statement ensures the connection is closed.
        with qwen_session.post(QWEN_API_URL, headers=QWEN_HEADERS, json=qwen_payload, stream=True, timeout=120) as r:
            # ### FIX 4: DETAILED ERROR HANDLING (THE MOST IMPORTANT FIX) ###
            # This checks the status code *before* trying to process the stream.
            # If it's a 400 or other error, we get the specific error message from the body.
            if r.status_code != 200:
                error_body = r.text
                print(f"Qwen API Error - Status: {r.status_code}, Body: {error_body}")
                error_msg = f"**API Error ({r.status_code}):**\n\nI couldn't get a response. The server said:\n\n`{error_body}`"
                yield error_msg
                full_reply = error_msg
            else:
                for line in r.iter_lines(decode_unicode=True):
                    if line and line.startswith("data: "):
                        data_str = line.split("data: ", 1)[1]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data.get("choices", [{}])[0].get("delta", {}).get("content")
                            if delta:
                                yield delta
                                full_reply += delta
                        except (json.JSONDecodeError, IndexError):
                            print(f"Could not parse stream line: {data_str}")
                            continue

    except requests.exceptions.RequestException as e:
        # This catches network-level errors (timeouts, DNS failures, etc.)
        print(f"Qwen API RequestException: {e}")
        error_msg = f"**Connection Error:**\n\nI couldn't connect to the Qwen service. Please check the network. Details: {e}"
        yield error_msg
        full_reply = error_msg
    
    # Save the complete bot response after the stream ends
    if full_reply:
        with app.app_context():
            # Save the assistant's reply in the same structured format for consistency.
            assistant_reply_structured = [{'type': 'text', 'text': full_reply.strip()}]
            save_msg(sid, "assistant", assistant_reply_structured)

# ==============================================================================
# Flask Routes (Minor changes for robustness)
# ==============================================================================
@app.route("/")
def index():
    return send_file('index.html')

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json
        if not data or 'session' not in data:
             return Response("Invalid request: 'session' is required.", status=400)
            
        sid = data["session"]
        text = data.get("text", "").strip()
        model = data.get("model", "workik")
        image_data = data.get("imageData", None)

        # Check if there's any input for the selected model
        if model == 'qwen' and not text and not image_data:
            return Response("For Qwen, 'text' or 'imageData' must be provided.", status=400)
        
        # === MODEL-BASED ROUTING ===
        if model == 'qwen':
            return Response(stream_with_context(get_qwen_response_stream(sid, text, image_data)), mimetype="text/plain; charset=utf-8")
        else: # workik
            if not text:
                return Response("Text input is required for the workik model.", status=400)
            
            # Using the new save_msg for consistency, even though it's just a string for workik
            save_msg(sid, "user", text)
            
            def gen_workik():
                current_payload = workik_payload_template.copy()
                current_payload["aiInput"] = text
                current_payload["editScript"]["messages"][0]["msg"] = text
                buffer = ""
                try:
                    with workik_session.post(workik_url, headers=workik_headers, json=current_payload, stream=True, timeout=30) as r:
                        r.raise_for_status()
                        for line in r.iter_lines(decode_unicode=True):
                            if line:
                                chunk = clean_workik_response(line)
                                if chunk:
                                    buffer += chunk
                                    yield chunk
                except requests.exceptions.RequestException as e:
                    print(f"Workik API Request error: {e}")
                    mock_error = f"🤖 **Connection Error**\n\nI couldn't reach the AI service. Please try again later. (Details: {e})"
                    yield mock_error
                    buffer = mock_error

                if buffer:
                    with app.app_context():
                        save_msg(sid, "bot", buffer.strip()) # "bot" role for workik
            
            return Response(stream_with_context(gen_workik()), mimetype="text/plain; charset=utf-8")
        
    except Exception as e:
        print(f"FATAL Chat endpoint error: {e}")
        import traceback
        traceback.print_exc()
        return Response(f"An unexpected server error occurred: {str(e)}", status=500)

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    # For local development, set debug=True to get auto-reloading and better error pages.
    # For production, debug should be False.
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)
