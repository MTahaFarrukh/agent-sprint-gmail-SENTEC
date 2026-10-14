"""Run this first: python check_env.py
Checks Python, packages, and your Gemini API key.
Set your key first:
  Windows (PowerShell):  $env:GEMINI_API_KEY="your_key"
  Mac/Linux:             export GEMINI_API_KEY="your_key"
Optional: set GEMINI_MODEL to choose a specific model name.
"""
import os
import sys

print("Python:", sys.version.split()[0])

def check(mod):
    try:
        __import__(mod)
        print(f"[ok] {mod}")
        return True
    except Exception as e:
        print(f"[missing] {mod}: {e}")
        return False

ok = check("google.genai")
check("pandas")
check("streamlit")

key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
if not key:
    print("[problem] No API key found. Set GEMINI_API_KEY first.")
    sys.exit(1)
if not ok:
    print("[problem] Run: pip install -r requirements.txt")
    sys.exit(1)

from google import genai

try:
    client = genai.Client(api_key=key)
    names = [m.name for m in client.models.list()]
    skip = ("image", "tts", "live", "embedding", "imagen", "veo", "audio", "aqa")
    usable = [n for n in names if "gemini" in n and not any(s in n for s in skip)]
    print("Some available models:", usable[:8])
    model = os.environ.get("GEMINI_MODEL")
    if not model:
        flash = [n for n in usable if "flash" in n]
        model = (flash or usable)[0]
    model = model.replace("models/", "")
    print("Testing model:", model)
    reply = client.models.generate_content(model=model, contents="Reply with exactly: OK")
    print("Model replied:", reply.text.strip())
    print("[ok] Everything works. Use this model name in your code:", model)
except Exception as e:
    print("[problem]", e)
    print("If you see 429 or quota errors, wait a minute or ask your volunteer for another key.")
    sys.exit(1)
