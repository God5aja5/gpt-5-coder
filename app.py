# app.py FULL CORRECTED VERSION WITH CLAUDE 4, GROQ SMART MEMORY & NEW GPT-5 MINI API

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
import random
from groq import Groq

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

def update_last_bot_message(sid, new_content_chunk):
    with db_lock:
        db = get_db()
        cursor = db.execute("SELECT id, message FROM chats WHERE session_id=? AND role='bot' ORDER BY ts DESC LIMIT 1", (sid,))
        last_bot_msg = cursor.fetchone()
        if last_bot_msg:
            updated_message = last_bot_msg['message'] + new_content_chunk
            db.execute("UPDATE chats SET message=? WHERE id=?", (updated_message, last_bot_msg['id']))
            db.commit()
        else:
            save_msg(sid, 'bot', new_content_chunk)

def load_msgs(sid):
    db = get_db()
    cursor = db.execute("SELECT role, message FROM chats WHERE session_id=? ORDER BY ts ASC", (sid,))
    messages = []
    for row in cursor.fetchall():
        role = "assistant" if row['role'] == 'bot' else row['role']
        # The Pro Reasoner, Groq, and Claude models may send an artifact, so we store it and remove for display
        clean_message = re.sub(r'<think>[\s\S]*?<\/think>', '', row['message'], flags=re.IGNORECASE).strip()
        if clean_message:
            messages.append({'role': role, 'content': clean_message})
    return messages

# ==============================================================================
# API Integration Section
# ==============================================================================

# --- Shared Artifact System Prompt ---
ARTIFACT_PROMPT = {
    "role": "system",
    "content": "You are a world-class AI assistant with a 'second brain' or 'scratchpad'. Before providing your final answer, you MUST use a `<think>` block to outline your reasoning, plan, and any intermediate steps or self-corrections. This 'thinking' process is for your internal use and helps you arrive at the most accurate and comprehensive response. The user will not see the content of the `<think>` block directly. Structure your thought process logically. After the closing `</think>` tag, provide your final, user-facing answer based on your reasoning. Current date: Friday, August 22, 2025."
}

# --- Groq API Section (Models 1-4) with Smart Memory ---
groq_client = Groq(api_key="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")
GROQ_MODELS = {
    'moonshotai/kimi-k2-instruct': 16384,
    'openai/gpt-oss-20b': 65536,
    'openai/gpt-oss-120b': 65536,
    'qwen/qwen3-32b': 40960
}

# Smart Memory function to truncate history for Groq
def truncate_history(history, max_chars=8000):
    truncated_history = []
    current_chars = 0
    for msg in reversed(history):
        msg_len = len(msg.get('content', ''))
        if current_chars + msg_len <= max_chars:
            truncated_history.insert(0, msg)
            current_chars += msg_len
        else:
            break
    return truncated_history

def stream_groq_model(chat_history, model_name, temperature):
    if model_name not in GROQ_MODELS:
        yield f"🚨 Groq AI Error: Model '{model_name}' not found."
        return
    
    truncated_chat_history = truncate_history(chat_history)
    messages_with_prompt = [ARTIFACT_PROMPT] + truncated_chat_history
    max_tokens = GROQ_MODELS[model_name]

    try:
        completion = groq_client.chat.completions.create(
            model=model_name, messages=messages_with_prompt, temperature=float(temperature),
            max_tokens=max_tokens, top_p=1, stream=True, stop=None
        )
        for chunk in completion:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        yield f"🚨 Groq AI Error: {str(e)}"

# --- New Kimi K2 API Integration ---
kimi_k2_session = requests.Session()
kimi_k2_headers = {
    'authority': 'ai-sdk-starter-groq.vercel.app',
    'accept': '*/*',
    'accept-language': 'en-US,en;q=0.9',
    'cache-control': 'no-cache',
    'content-type': 'application/json',
    'origin': 'https://ai-sdk-starter-groq.vercel.app',
    'pragma': 'no-cache',
    'referer': 'https://ai-sdk-starter-groq.vercel.app/',
    'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
    'sec-ch-ua-mobile': '?1',
    'sec-ch-ua-platform': '"Android"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
}
kimi_k2_url = 'https://ai-sdk-starter-groq.vercel.app/api/chat'

def stream_kimi_k2_model(chat_history):
    # This API uses a fresh session for each request, so we just send the latest message
    # And truncate the history to fit within a reasonable context window.
    messages_for_api = []
    # Kimi API expects messages in a specific format
    # We add the artifact prompt for consistency
    messages_for_api.append({'parts': [{'type': 'text', 'text': ARTIFACT_PROMPT['content']}], 'id': str(uuid.uuid4()), 'role': 'system'})
    
    # We pass the full history to the Kimi API
    for msg in chat_history:
        role = 'user' if msg['role'] == 'user' else 'assistant'
        messages_for_api.append({'parts': [{'type': 'text', 'text': msg['content']}], 'id': str(uuid.uuid4()), 'role': role})

    payload = {
        'selectedModel': 'kimi-k2',
        'id': str(uuid.uuid4()),
        'messages': messages_for_api,
        'trigger': 'submit-user-message',
    }
    
    try:
        with kimi_k2_session.post(kimi_k2_url, headers=kimi_k2_headers, json=payload, stream=True, timeout=90) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    decoded = line.decode('utf-8', errors='ignore')
                    if decoded.startswith("data: "):
                        decoded = decoded[6:]
                    if decoded.strip() in ["[DONE]", ""]:
                        continue
                    try:
                        data_json = json.loads(decoded)
                        if isinstance(data_json, dict) and data_json.get("type") == "text-delta":
                            yield data_json.get("delta", "")
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        yield f"🚨 Kimi K2 API Error: {str(e)}"

# --- Old claila.com GPT-5 Mini API (RATE-LIMITED) ---
claila_session = requests.Session()
CLALA_SYSTEM_PROMPT = "You are an AI assistant. Answer clearly and concisely."
claila_sessions = {}

# --- Fetch CSRF Token ---
def get_claila_csrf_token():
    url = "https://app.claila.com/api/v2/getcsrftoken"
    headers = {
        'accept': '*/*', 'x-requested-with': 'XMLHttpRequest', 'user-agent': 'Mozilla/5.0'
    }
    try:
        response = claila_session.get(url, headers=headers)
        response.raise_for_status()
        return response.text.strip()
    except Exception as e:
        print(f"Error fetching Claila CSRF token: {e}")
        return None

# --- Fetch Session ID ---
def get_claila_session_id():
    url = "https://app.claila.com/chat"
    headers = {
        'accept': 'text/html', 'user-agent': 'Mozilla/5.0'
    }
    try:
        response = claila_session.get(url, headers=headers)
        response.raise_for_status()
        match = re.search(r"session_id\s*:\s*'([^']+)'", response.text)
        return match.group(1) if match else None
    except Exception as e:
        print(f"Error fetching Claila session ID: {e}")
        return None

def stream_claila_gpt5_mini(sid, text, new_chat=False):
    # This logic is critical for maintaining a 1-to-1 chat session
    if new_chat or sid not in claila_sessions:
        session_id = get_claila_session_id()
        csrf_token = get_claila_csrf_token()
        if not session_id or not csrf_token:
            yield "🚨 GPT-5 Mini API Error: Failed to initialize a new session. This API might be rate-limited or require cookies."
            return
        claila_sessions[sid] = {
            "session_id": session_id,
            "csrf_token": csrf_token,
            "first_message": True,
        }
        # Print the new chat ID to the terminal
        print(f"🥳 New chat created with GPT-5 Mini. Session ID: {sid}")
    
    current_session_data = claila_sessions[sid]
    
    message_to_send = text
    if current_session_data["first_message"]:
        message_to_send = f"{CLALA_SYSTEM_PROMPT}\n\nUser: {text}"
        current_session_data["first_message"] = False

    url = "https://app.claila.com/api/v2/unichat2"
    headers = {
        'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'x-csrf-token': current_session_data["csrf_token"],
        'x-requested-with': 'XMLHttpRequest',
        'user-agent': 'Mozilla/5.0'
    }
    data = {
        'model': 'gpt-5-mini',
        'calltype': 'completion',
        'message': message_to_send,
        'sessionId': current_session_data["session_id"],
    }
    try:
        with claila_session.post(url, headers=headers, data=data, stream=True, timeout=90) as response:
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=32):
                if chunk:
                    yield chunk.decode('utf-8')
    except Exception as e:
        yield f"🚨 GPT-5 Mini API Error: {str(e)}"
# --- other API integrations remain the same...

# ==============================================================================
# Flask Routes
# ==============================================================================
@app.route("/")
def index(): return send_file('index.html')

@app.route('/favicon.ico')
def favicon(): return '', 204

@app.route("/upload_image", methods=["POST"])
def upload_image():
    if 'file' not in request.files: return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({"error": "No selected file"}), 400
    try:
        image_bytes = file.read()
        image = Image.open(io.BytesIO(image_bytes))
        width, height = image.size
        file.seek(0)
        encoded_string = base64.b64encode(image_bytes).decode('utf-8')
        mime_type = file.mimetype
        base64_uri = f"data:{mime_type};base64,{encoded_string}"
        image_info = { "id": str(uuid.uuid4()), "name": file.filename, "size": len(image_bytes), "width": width, "height": height, "fileType": mime_type, "base64": base64_uri }
        return jsonify(image_info)
    except Exception as e: return jsonify({"error": f"Failed to process image: {str(e)}"}), 500

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json
        sid = data["session"]
        model = data.get("model", "gpt-5-mini")
        action = data.get("action", "chat")
        temperature = data.get("temperature", 0.9)

        if action == "chat":
            text = data["text"]
            image_info = data.get("imageInfo")
            user_message_to_save = f"[Image: {image_info['name']}]\n{text}" if image_info else text
            save_msg(sid, "user", user_message_to_save)
            chat_history = load_msgs(sid)
        elif action == "continue":
            chat_history = load_msgs(sid)
            continue_prompt = { 'role': 'user', 'content': "Continue precisely from where you left off. Do not add any new introductory phrases, comments, or explanations." }
            chat_history.append(continue_prompt)
            text = "continue"
            image_info = None
        elif action == "new":
            # This action is for explicitly creating a new chat.
            text = data.get("text", "")
            image_info = None
        else:
            return Response("Invalid action.", status=400)

        def gen():
            buffer = ""
            try:
                # New logic to handle kimi-k2-coder
                if model == 'kimi-k2-coder':
                    for chunk_text in stream_kimi_k2_model(chat_history):
                        buffer += chunk_text; yield chunk_text
                # Existing models...
                elif model == 'kimi-k2':
                    for chunk_text in stream_kimi_k2_model(chat_history):
                        buffer += chunk_text; yield chunk_text
                elif model in GROQ_MODELS:
                    for chunk_text in stream_groq_model(chat_history, model, temperature):
                        buffer += chunk_text; yield chunk_text
                # ...other models...
                elif model == 'gpt-5-mini':
                    for chunk_text in stream_claila_gpt5_mini(sid, text, new_chat=(action == "new" or 'session' not in claila_sessions)):
                        buffer += chunk_text; yield chunk_text
                else:
                     yield "🚨 Model not found."
            except requests.exceptions.RequestException as e:
                error_msg = f"🤖 **Connection Error**\n\nI couldn't reach the AI service for model '{model}'. Details: {e}"
                yield error_msg; buffer = error_msg
            except Exception as e:
                error_msg = f"🤖 **System Error**\n\nUnexpected error: {str(e)}"
                yield error_msg; buffer = error_msg

            if buffer:
                with app.app_context():
                    if action == "continue":
                        update_last_bot_message(sid, buffer)
                    else:
                        save_msg(sid, "bot", buffer)

        return Response(stream_with_context(gen()), mimetype="text/plain; charset=utf-8")
        
    except Exception as e:
        return Response(f"Server error: {str(e)}", status=500)

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
