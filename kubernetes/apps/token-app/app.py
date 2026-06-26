import os
import sys
import json
import urllib.request
import ssl
import numpy as np
import base64
from flask import Flask, render_template, request, jsonify
from sklearn.decomposition import PCA
import tiktoken

app = Flask(__name__)

# Load Ollama configurations from environment variables
OLLAMA_URL = os.environ.get("OLLAMA_URL", "https://192.168.0.201")
OLLAMA_USER = os.environ.get("OLLAMA_USER", "")
OLLAMA_PASSWORD = os.environ.get("OLLAMA_PASSWORD", "")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")

# Setup unverified SSL context for local/self-signed certificates
ssl_context = ssl._create_unverified_context()

def get_ollama_headers():
    headers = {
        "Content-Type": "application/json",
        "Host": "ollama.home"
    }
    if OLLAMA_USER and OLLAMA_PASSWORD:
        auth_str = f"{OLLAMA_USER}:{OLLAMA_PASSWORD}"
        auth_bytes = auth_str.encode("utf-8")
        auth_b64 = base64.b64encode(auth_bytes).decode("utf-8")
        headers["Authorization"] = f"Basic {auth_b64}"
    return headers

def get_embedding(text):
    """Fetch 768-dimension vector embedding from local Ollama service."""
    # Handle local port-forwarding or internal K8s URL override
    api_url = OLLAMA_URL
    if not api_url.endswith("/api/embeddings") and not api_url.endswith("/api/embeddings/"):
        api_url = f"{api_url.rstrip('/')}/api/embeddings"
        
    data = json.dumps({
        "model": EMBEDDING_MODEL,
        "prompt": text
    }).encode("utf-8")
    
    headers = get_ollama_headers()
    # Bypass Host header if querying localhost or internal kubernetes DNS directly
    if "localhost" in api_url or "127.0.0.1" in api_url or "svc.cluster.local" in api_url:
        headers.pop("Host", None)
        
    req = urllib.request.Request(api_url, data=data, headers=headers, method="POST")
    try:
        # If querying HTTP localhost or internal K8s, we don't need the custom SSL context
        if api_url.startswith("https"):
            response_file = urllib.request.urlopen(req, context=ssl_context)
        else:
            response_file = urllib.request.urlopen(req)
            
        with response_file as response:
            res = json.loads(response.read().decode("utf-8"))
            return res.get("embedding")
    except Exception as e:
        print(f"Error fetching embedding for '{text}': {e}", file=sys.stderr)
        return None

def cosine_similarity(v1, v2):
    v1 = np.array(v1)
    v2 = np.array(v2)
    dot_product = np.dot(v1, v2)
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    return float(dot_product / (norm_v1 * norm_v2))

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/tokenize", methods=["POST"])
def tokenize():
    data = request.json or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"tokens": [], "stats": {}})
        
    try:
        # Load cl100k_base (used by GPT-4 and Qwen) BPE tokenizer
        enc = tiktoken.get_encoding("cl100k_base")
        token_ids = enc.encode(text)
        
        tokens = []
        for tid in token_ids:
            token_bytes = enc.decode_single_token_bytes(tid)
            token_str = token_bytes.decode("utf-8", errors="replace")
            tokens.append({
                "id": tid,
                "text": token_str
            })
            
        stats = {
            "num_characters": len(text),
            "num_tokens": len(token_ids),
            "ratio": round(len(text) / len(token_ids), 2) if len(token_ids) > 0 else 0
        }
        
        return jsonify({"tokens": tokens, "stats": stats})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/similarity", methods=["POST"])
def similarity():
    data = request.json or {}
    text1 = data.get("text1", "")
    text2 = data.get("text2", "")
    
    if not text1 or not text2:
        return jsonify({"error": "Both text inputs are required"}), 400
        
    v1 = get_embedding(text1)
    v2 = get_embedding(text2)
    
    if v1 is None or v2 is None:
        return jsonify({"error": "Failed to generate embeddings from Ollama"}), 500
        
    sim = cosine_similarity(v1, v2)
    return jsonify({"similarity": sim})

@app.route("/api/project", methods=["POST"])
def project():
    """Receive list of texts, fetch embeddings, and reduce to 2D using PCA."""
    data = request.json or {}
    texts = data.get("texts", [])
    if not texts:
        return jsonify([])
        
    # Clean list
    texts = [t.strip() for t in texts if t.strip()]
    if len(texts) < 2:
        return jsonify({"error": "Please enter at least 2 items to visualize"}), 400
        
    vectors = []
    valid_texts = []
    
    for text in texts:
        vector = get_embedding(text)
        if vector is not None:
            vectors.append(vector)
            valid_texts.append(text)
            
    if len(vectors) < 2:
        return jsonify({"error": "Failed to generate enough valid embeddings"}), 500
        
    vectors_np = np.array(vectors)
    
    # Run Principal Component Analysis (PCA) to reduce 768 dimensions to 2D (X, Y)
    pca = PCA(n_components=2)
    coords = pca.fit_transform(vectors_np).tolist()
    
    result = []
    for t, c in zip(valid_texts, coords):
        result.append({
            "text": t,
            "x": round(c[0], 4),
            "y": round(c[1], 4)
        })
        
    return jsonify(result)

@app.route("/api/math", methods=["POST"])
def vector_math():
    data = request.json or {}
    a = data.get("a", "").strip()
    b = data.get("b", "").strip()
    c = data.get("c", "").strip()
    targets = data.get("targets", [])
    
    if not a or not b or not c:
        return jsonify({"error": "Inputs A, B, and C are required"}), 400
        
    v_a = get_embedding(a)
    v_b = get_embedding(b)
    v_c = get_embedding(c)
    
    if v_a is None or v_b is None or v_c is None:
        return jsonify({"error": "Failed to generate embeddings for components"}), 500
        
    # Vector arithmetic: Result = A - B + C (e.g. King - Man + Woman)
    target_vector = np.array(v_a) - np.array(v_b) + np.array(v_c)
    
    results = []
    for term in targets:
        term = term.strip()
        if not term:
            continue
        v_term = get_embedding(term)
        if v_term is not None:
            sim = cosine_similarity(target_vector, v_term)
            results.append({
                "text": term,
                "similarity": round(sim, 4)
            })
            
    # Sort by descending similarity
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return jsonify(results)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
