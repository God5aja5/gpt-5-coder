import os, time, json, sqlite3, re, threading
from flask import Flask, Response, stream_with_context, request, jsonify, g
import requests

# ==============================================================================
# Database Setup (No changes needed here, it was already solid)
# ==============================================================================
DB = "chat_history.db"
db_lock = threading.Lock()

app = Flask(__name__)

def get_db():
    """Get database connection with proper timeout and row factory"""
    if 'db' not in g:
        g.db = sqlite3.connect(DB, timeout=10, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    """Close database connection after each request"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    """Initialize database with proper table structure"""
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
    """Save message to database with thread safety"""
    with db_lock:
        db = get_db()
        db.execute("INSERT INTO chats(session_id, role, message) VALUES (?,?,?)", (sid, role, msg))
        db.commit()

def load_msgs(sid):
    """Load messages from database"""
    db = get_db()
    cursor = db.execute("SELECT role, message FROM chats WHERE session_id=? ORDER BY ts ASC", (sid,))
    return [{'role': row['role'], 'message': row['message']} for row in cursor.fetchall()]

# ==============================================================================
# Workik API Integration (No changes needed here)
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

payload = {
    'aiInput': 'Hello',
    'defaultContext': [
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
                'platform': 'github',
            },
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
            'default_button_text': 'Add Database',
        },
        {
            'id': '5e808426-8981-4482-b0de-263749ae5aa7',
            'title': 'Rest API Designs',
            'type': 'request',
            'description': '',
            'requests': [],
            'default_add': True,
            'default_button_text': 'Add APIs',
        },
        {
            'id': '749bef72-a509-49ce-8798-c573ac142725',
            'title': 'Programming Language',
            'type': 'input',
            'description': '',
            'value_text': '',
            'default_add': True,
            'default_button_text': 'Add value',
        },
        {
            'id': '15c85d87-0da2-40c1-acd0-750655e7fa5e',
            'title': 'Relevant Packages',
            'type': 'checklist',
            'description': '',
            'options_list': [],
            'seperator_text': '',
            'default_add': True,
            'default_button_text': 'Add Options',
        },
    ],
    'editScript': {
        'id': '4b10ac62-51be-4db7-a240-4f28e59aecf8',
        'name': 'My workspace',
        'messages': [
            {
                'type': 'question',
                'responseType': 'code',
                'sendTo': 'ai',
                'msg': 'Hello',
                'created_by': '',
                'time': '2025-08-11 00:50:42',
                'id': '1754873442623_8nsyg35ho',
                'group_id': None,
            },
        ],
        'status': 'own',
        'context': {
            'fd4a1e85-534f-4d73-8822-99161d46e0c7': {},
            '971ede3c-b26b-4b4a-a3ba-02b1b5ce0dd0': {},
            '5e808426-8981-4482-b0de-263749ae5aa7': {},
            '749bef72-a509-49ce-8798-c573ac142725': '',
            '15c85d87-0da2-40c1-acd0-750655e7fa5e': {},
        },
        'response_type': 'code',
        'created_by': '',
    },
    'all_messages': [],
    'codingLanguage': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0ZXh0IjoiQUksIGZ1bmN0aW9uIGFzIGEgY29kZSBnZW5lcmF0b3IuIEFzc2lzdCB1c2VycyBpbiBjcmVhdGluZyBjb2RlIGFjcm9zcyB2YXJpb3VzIHByb2dyYW1taW5nIGxhbmd1YWdlcyBhbmQgZnJhbWV3b3JrcyBieSBhbGxvd2luZyB0aGVtIHRvIHNwZWNpZnkgdGhlaXIgcmVxdWlyZW1lbnRzLCBzdWNoIGFzIHRoZSBwcm9ncmFtbWluZyBsYW5ndWFnZSwgZGVzaXJlZCBmZWF0dXJlcywgYW5kIHRhcmdldCBwbGF0Zm9ybS4gR2VuZXJhdGUgY2xlYW4sIGVmZmljaWVudCBjb2RlIHRhaWxvcmVkIHRvIHRoZXNlIHNwZWNpZmljYXRpb25zLCBlbnN1cmluZyBhZGhlcmVuY2UgdG8gYmVzdCBwcmFjdGljZXMgZm9yIHBlcmZvcm1hbmNlLCBzZWN1cml0eSwgYW5kIG1haW50YWluYWJpbGl0eS4gSW5jbHVkZSBzdXBwb3J0IGZvciBjb21tb24gdGFza3MgbGlrZSBkYXRhIHByb2Nlc3NpbmcsIEFQSSBpbnRlZ3JhdGlvbiwgdXNlciBhdXRoZW50aWNhdGlvbiwgYW5kIFVJIGRldmVsb3BtZW50LiBQcm92aWRlIG9wdGlvbnMgZm9yIGN1c3RvbWl6YXRpb24sIHRlc3RpbmcsIGFuZCBkZXBsb3ltZW50LCBoZWxwaW5nIHVzZXJzIHRvIHNlYW1sZXNzbHkgaW50ZWdyYXRlIHRoZSBnZW5lcmF0ZWQgY29kZSBpbnRvIHRoZWlyIHByb2plY3RzLiIsImlhdCI6MTcyMzc5ODU2OX0.5I-NABUTyopkPbmOqb8vgxvn1pzYe-gx0HV0Px33iLM',
    'token_type': 'workik.openai:gpt_5_mini',
    'uploaded_files': {},
    'msg_type': 'message',
    'wk_ld': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0eXBlIjoibG9jYWwiLCJzZXNzaW9uX2lkIjoiMTc1NDg3MzQzMSIsInJlcXVlc3RfY291bnQiOjAsImV4cCI6MTc1NTQ3ODIzMX0.o1_64-viSF1PiayWY0La9dUleHUrUWxnhr-nL-db_-E',
    'wk_ck': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0eXBlIjoiY29va2llIiwic2Vzc2lvbl9pZCI6IjE3NTQ4NzM0MzEiLCJyZXF1ZXN0X2NvdW50IjowLCJleHAiOjE3NTU0NzgyMzF9.Di9RTlHcNp51ZSQVgX71G6oEHYGM7Khucz7Ixnwahtc',
}

url = 'https://wfhbqniijcsamdp2v3i6nts4ke0ebkyj.lambda-url.us-east-1.on.aws/api_ai_playground/ai/playground/ai/trigger'

def clean_response(text):
    """Extract content from API response"""
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
# The UI (HTML, CSS, JavaScript) - THIS IS WHERE THE FIXES ARE
# ==============================================================================
UI = """<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>🤖 Mini GPT Pro</title>
<!-- Libraries for Markdown and Syntax Highlighting -->
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>

<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');

:root {
  --bg-primary: #0f0f23;
  --bg-secondary: #1a1a2e;
  --bg-tertiary: #16213e;
  --user-bg: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  --bot-bg: linear-gradient(135deg, #16213e 0%, #0f3460 100%);
  --accent: #00d4aa;
  --accent-hover: #00b894;
  --text-primary: #e2e8f0;
  --text-secondary: #94a3b8;
  --border: #334155;
  --shadow: rgba(0, 0, 0, 0.3);
  --glow: rgba(0, 212, 170, 0.2);
  --code-bg: #0c0c1f;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body, html {
  height: 100%;
  background: linear-gradient(135deg, var(--bg-primary) 0%, var(--bg-secondary) 100%);
  color: var(--text-primary);
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  overflow: hidden; /* IMPORTANT: Prevents the whole page from scrolling */
}

/* ====================================================== */
/* ========== BRO, THIS IS THE MAIN UI FIX ============ */
/* ====================================================== */

.container {
  height: 100vh; /* Make container full viewport height */
  display: flex; /* CRITICAL: Use Flexbox for layout */
  flex-direction: column; /* Stack children (header, chat, input) vertically */
  max-width: 1200px;
  margin: 0 auto;
  background: rgba(26, 26, 46, 0.8);
  backdrop-filter: blur(10px);
  border-left: 1px solid var(--border);
  border-right: 1px solid var(--border);
}

.fullscreen { max-width: 100%; height: 100vh; border: none; }

.header {
  padding: 1rem 1.5rem;
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 0.5rem;
  box-shadow: 0 2px 10px var(--shadow);
  flex-shrink: 0; /* CRITICAL: Prevents the header from shrinking */
}

.chat {
  flex-grow: 1; /* CRITICAL: Makes the chat area fill ALL available space */
  overflow-y: auto; /* CRITICAL: Makes ONLY the chat area scrollable */
  min-height: 0; /* CRITICAL FLEXBOX HACK: Allows the chat area to shrink properly */
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  scroll-behavior: smooth;
}

.input-container {
  padding: 1rem 1.5rem;
  background: var(--bg-tertiary);
  border-top: 1px solid var(--border);
  display: flex;
  gap: 0.75rem;
  align-items: flex-end;
  flex-shrink: 0; /* CRITICAL: Prevents the input area from shrinking */
}
/* ====================================================== */
/* ============= END OF THE MAIN UI FIX ================= */
/* ====================================================== */

.header h1 {
  font-size: 1.2rem;
  font-weight: 600;
  background: linear-gradient(135deg, var(--accent), #667eea);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.status {
  margin-left: auto;
  margin-right: 1rem;
  padding: 0.25rem 0.75rem;
  background: rgba(0, 212, 170, 0.1);
  border: 1px solid var(--accent);
  border-radius: 20px;
  font-size: 0.75rem;
  color: var(--accent);
  transition: all 0.3s ease;
}

.fullscreen-btn {
  width: 32px; height: 32px; border: none; border-radius: 6px;
  background: rgba(255, 255, 255, 0.1); color: var(--text-primary); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.2s ease; font-size: 14px;
}
.fullscreen-btn:hover { background: rgba(0, 212, 170, 0.2); color: var(--accent); }

.chat::-webkit-scrollbar { width: 6px; }
.chat::-webkit-scrollbar-track { background: var(--bg-secondary); }
.chat::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
.chat::-webkit-scrollbar-thumb:hover { background: var(--accent); }

.message {
  display: flex; align-items: flex-start; gap: 0.75rem;
  max-width: 85%; animation: messageSlide 0.3s ease-out;
}
.message.user { align-self: flex-end; flex-direction: row-reverse; }

.avatar {
  width: 32px; height: 32px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.875rem; font-weight: 600; flex-shrink: 0;
}
.user .avatar { background: var(--user-bg); color: white; }
.bot .avatar { background: var(--bot-bg); color: var(--accent); border: 2px solid var(--accent); }

.bubble {
  padding: 1rem 1.25rem; border-radius: 1rem;
  font-size: 0.95rem; line-height: 1.5;
  white-space: pre-wrap; word-wrap: break-word;
  position: relative; box-shadow: 0 4px 12px var(--shadow);
}
.user .bubble { background: var(--user-bg); color: white; border-bottom-right-radius: 0.25rem; }
.bot .bubble { background: var(--bg-tertiary); border: 1px solid var(--border); border-bottom-left-radius: 0.25rem; }
.typing { opacity: 0.7; }
.typing::after { content: ' ▋'; animation: blink 1s infinite; }

/* BRO, HERE ARE THE UPGRADED STYLES FOR CODE BLOCKS */
.bot .bubble pre {
  background-color: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0; /* Remove padding here, add it to children */
  margin: 1em 0;
  overflow-x: auto; /* THIS IS THE MAGIC FIX for wide code */
  position: relative;
}
.bot .bubble code {
  font-family: 'Fira Code', 'Courier New', monospace;
  font-size: 0.9em;
  background: none;
  padding: 1em; /* Add padding here instead of pre */
  display: block; /* Make it a block to hold padding */
  overflow-x: visible; /* Let it scroll inside the pre */
}
/* THIS IS THE NEW HEADER FOR THE CODE BLOCK (WITH COPY BUTTON) */
.code-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background-color: #2a2a40;
  color: var(--text-secondary);
  padding: 0.5em 1em;
  border-top-left-radius: 8px;
  border-top-right-radius: 8px;
  border-bottom: 1px solid var(--border);
  font-size: 0.8em;
  text-transform: lowercase;
}
.copy-btn {
  background: var(--bg-secondary);
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 0.25em 0.5em;
  cursor: pointer;
  transition: all 0.2s ease;
}
.copy-btn:hover { background: var(--accent); color: var(--bg-primary); }
.bot .bubble p { margin-bottom: 0.5rem; }
.bot .bubble ul, .bot .bubble ol { margin-left: 1.5rem; margin-bottom: 0.5rem; }

.input-wrapper { flex: 1; position: relative; }
#input {
  width: 100%; padding: 0.75rem 1rem; border: 2px solid var(--border);
  border-radius: 1rem; background: var(--bg-secondary);
  color: var(--text-primary); font-size: 0.95rem; font-family: inherit;
  resize: none; max-height: 120px; min-height: 44px; transition: all 0.2s ease;
}
#input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--glow); }
#input::placeholder { color: var(--text-secondary); }

.btn {
  padding: 0.75rem 1.25rem; border: none; border-radius: 1rem;
  font-size: 0.875rem; font-weight: 600; cursor: pointer;
  transition: all 0.2s ease; display: flex; align-items: center;
  gap: 0.5rem; white-space: nowrap;
}
.btn-primary { background: linear-gradient(135deg, var(--accent), #00b894); color: white; box-shadow: 0 4px 12px rgba(0, 212, 170, 0.3); }
.btn-primary:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(0, 212, 170, 0.4); }
.btn-secondary { background: #dc2626; color: white; box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3); }
.btn-secondary:hover:not(:disabled) { background: #b91c1c; transform: translateY(-1px); }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }

/* BRO, I ADDED THIS BUTTON */
.btn-new-chat {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  padding: 0.5rem 1rem;
  margin-right: 1rem;
}
.btn-new-chat:hover {
  background: var(--bg-tertiary);
  border-color: var(--accent);
  color: var(--accent);
}

@keyframes messageSlide { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
@keyframes blink { 0%, 50% { opacity: 1; } 51%, 100% { opacity: 0; } }

@media (max-width: 768px) {
  .container { border-left: none; border-right: none; }
  .message { max-width: 95%; }
  .header { padding: 0.75rem 1rem; }
  .input-container { padding: 0.75rem 1rem; }
  .btn { padding: 0.75rem 1rem; font-size: 0.8rem; }
}
</style>
</head>
<body>
<div class="container" id="container">
  <div class="header">
    <button id="newChatBtn" class="btn btn-new-chat" onclick="startNewChat()" title="Start a New Chat">+ New Chat</button>
    <h1>🤖 Mini GPT Pro</h1>
    <div class="status" id="status">Online</div>
    <button class="fullscreen-btn" id="fullscreenBtn" onclick="toggleFullscreen()" title="Toggle Fullscreen">⛶</button>
  </div>
  <div class="chat" id="chat"></div>
  <div class="input-container">
    <div class="input-wrapper">
      <textarea id="input" placeholder="Type your message..." autocomplete="off" rows="1"></textarea>
    </div>
    <button id="send" class="btn btn-primary" onclick="send()"><span>Send</span></button>
    <button id="stop" class="btn btn-secondary" style="display:none" onclick="abortReq()"><span>Stop</span></button>
  </div>
</div>

<script>
let session = localStorage.getItem("sid") || Date.now().toString();
localStorage.setItem("sid", session);
let ctrl = null;
let isTyping = false;
let isFullscreen = false;

const input = document.getElementById("input");
const chatContainer = document.getElementById("chat");

input.addEventListener("input", function() {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 120) + "px";
});
input.addEventListener("keydown", function(e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });

function toggleFullscreen() {
  const container = document.getElementById("container");
  const btn = document.getElementById("fullscreenBtn");
  isFullscreen = !isFullscreen;
  container.classList.toggle("fullscreen", isFullscreen);
  btn.title = isFullscreen ? "Exit Fullscreen" : "Toggle Fullscreen";
}

function startNewChat() {
  if (ctrl) { ctrl.abort(); }
  session = Date.now().toString();
  localStorage.setItem("sid", session);
  chatContainer.innerHTML = "";
  isTyping = false;
  document.getElementById("send").style.display = "inline-flex";
  document.getElementById("stop").style.display = "none";
  setStatus("Online");
  input.value = "";
  input.style.height = "auto";
  addMessage("bot", "New chat started. How can I help you today?");
  input.focus();
}

function addMessage(role, txt, isTyping = false) {
  const messageDiv = document.createElement("div");
  messageDiv.className = `message ${role}`;
  
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "U" : "🤖";
  
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (isTyping) bubble.classList.add("typing");
  
  if (role === 'user') {
    renderContent(bubble, txt);
  } else {
    bubble.textContent = txt; // Just set plain text for now, render markdown later
  }
  
  messageDiv.appendChild(avatar);
  messageDiv.appendChild(bubble);
  chatContainer.appendChild(messageDiv);
  
  messageDiv.scrollIntoView({ behavior: "smooth", block: "end" });
  return bubble;
}

// BRO, THIS FUNCTION IS NOW SMARTER. IT ADDS THE COPY BUTTON!
function renderContent(element, markdownText) {
    // Use DOMPurify here if you were in production for security
    element.innerHTML = marked.parse(markdownText || '', { gfm: true, breaks: true, smartLists: true });
    
    element.querySelectorAll('pre').forEach(pre => {
        const code = pre.querySelector('code');
        if (!code) return;

        // Try to find language, default to 'plaintext'
        const language = [...code.classList].find(cls => cls.startsWith('language-'))?.replace('language-', '') || 'plaintext';
        
        // Create the code header
        const header = document.createElement('div');
        header.className = 'code-header';
        
        const langSpan = document.createElement('span');
        langSpan.textContent = language;
        
        const copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn';
        copyBtn.textContent = 'Copy';
        copyBtn.onclick = () => {
            navigator.clipboard.writeText(code.innerText).then(() => {
                copyBtn.textContent = 'Copied!';
                setTimeout(() => { copyBtn.textContent = 'Copy'; }, 2000);
            }).catch(err => {
                copyBtn.textContent = 'Error';
                console.error('Failed to copy text: ', err);
            });
        };
        
        header.appendChild(langSpan);
        header.appendChild(copyBtn);
        
        // Insert the header before the code inside the pre tag
        pre.insertBefore(header, pre.firstChild);
        
        // Apply syntax highlighting
        hljs.highlightElement(code);
    });
}


async function loadHistory() {
  try {
    const res = await fetch("/history?session=" + session);
    if (!res.ok) throw new Error(`Server responded with ${res.status}`);
    const msgs = await res.json();
    chatContainer.innerHTML = '';
    msgs.forEach(m => {
        const bubble = addMessage(m.role, m.message);
        if (m.role === 'bot') {
            renderContent(bubble, m.message);
        }
    });
  } catch (error) { 
    console.error("Failed to load history:", error); 
    addMessage("bot", "Could not load previous chat history.");
  }
}

function setStatus(text, color = "#00d4aa") {
  const status = document.getElementById("status");
  status.textContent = text;
  status.style.color = color;
  status.style.borderColor = color;
  const rgb = color === "#00d4aa" ? "0, 212, 170" : color === "#fbbf24" ? "251, 191, 36" : "220, 38, 38";
  status.style.background = `rgba(${rgb}, 0.1)`;
}

// BRO, THE SEND FUNCTION IS NOW MORE ROBUST AND EFFICIENT
async function send() {
  const msg = input.value.trim();
  if (!msg || isTyping) return;
  
  input.value = "";
  input.style.height = "auto";
  addMessage("user", msg);
  
  isTyping = true;
  setStatus("Typing...", "#fbbf24");
  document.getElementById("send").style.display = "none";
  document.getElementById("stop").style.display = "inline-flex";

  ctrl = new AbortController();
  const botBubble = addMessage("bot", "", true);

  try {
    const res = await fetch("/chat", {
      method: "POST",
      signal: ctrl.signal,
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({session, text: msg})
    });

    if (!res.ok) throw new Error(`HTTP Error: ${res.status} ${res.statusText}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    
    botBubble.classList.remove("typing"); // Remove typing early to just show text
    
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, {stream: true});
      botBubble.textContent = buffer; // Super fast text update
      botBubble.parentElement.scrollIntoView({ behavior: "auto", block: "end" });
    }
    
    const finalContent = buffer.trim() || "No response received.";
    renderContent(botBubble, finalContent); // Heavy rendering happens only ONCE
    botBubble.parentElement.scrollIntoView({ behavior: "smooth", block: "end" });
    setStatus("Online");
    
  } catch (error) {
    botBubble.classList.remove("typing");
    if (error.name !== "AbortError") {
      renderContent(botBubble, `**Error:** ${error.message}`);
      setStatus("Error", "#dc2626");
    } else {
      renderContent(botBubble, "Request stopped by user.");
      setStatus("Stopped", "#dc2626");
    }
  } finally {
    isTyping = false;
    document.getElementById("send").style.display = "inline-flex";
    document.getElementById("stop").style.display = "none";
  }
}

function abortReq() {
  if (ctrl) {
    ctrl.abort();
  }
}

// Initial setup
loadHistory();
input.focus();
</script>
</body>
</html>"""

# ==============================================================================
# Flask Routes
# ==============================================================================
@app.route("/")
def index():
    return UI

@app.route("/history")
def history():
    sid = request.args.get("session")
    if not sid:
        return jsonify([])
    messages = load_msgs(sid)
    return jsonify(messages)

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json
        # BRO, ADDED THIS CHECK FOR MORE ROBUSTNESS
        if not data or 'session' not in data or 'text' not in data:
            return Response("Invalid request data. 'session' and 'text' are required.", status=400)
            
        sid, text = data["session"], data["text"]
        save_msg(sid, "user", text)

        def gen():
            current_payload = payload.copy()
            current_payload["aiInput"] = text
            current_payload["editScript"]["messages"][0]["msg"] = text
            buffer = ""

            try:
                # BRO, THIS TRY/EXCEPT BLOCK HANDLES API FAILURES GRACEFULLY
                with session.post(url, headers=headers, json=current_payload, stream=True, timeout=30) as r:
                    r.raise_for_status() # Will raise an exception for 4xx/5xx responses
                    for line in r.iter_lines(decode_unicode=True):
                        if line:
                            chunk = clean_response(line)
                            if chunk:
                                buffer += chunk
                                yield chunk
                                
            except requests.exceptions.RequestException as e:
                print(f"API Request error: {e}")
                # Provide a user-friendly fallback message on API failure
                mock_error = f"🤖 **Connection Error**\\n\\nI couldn't reach the AI service. Please check your connection or try again later. (Details: {e})"
                yield mock_error # Stream the error message back to the user
                buffer = mock_error

            # Save the complete response after the stream ends
            if buffer:
                # Use app_context to ensure db connection is available in this thread
                with app.app_context():
                    save_msg(sid, "bot", buffer.strip())

        return Response(stream_with_context(gen()), mimetype="text/plain; charset=utf-8")
        
    except Exception as e:
        print(f"Chat endpoint error: {e}")
        return Response(f"An unexpected server error occurred: {str(e)}", status=500)

if __name__ == "__main__":
    init_db()
    # Render provides the port number in the PORT environment variable
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
