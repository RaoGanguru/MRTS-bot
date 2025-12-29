
import os
from dotenv import load_dotenv
import ollama

load_dotenv()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

def chat(messages, stream=False):
    """
    messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
    """
    return ollama.chat(model=OLLAMA_MODEL, messages=messages, stream=stream)

def answer(system_prompt: str, user_prompt: str) -> str:
    msgs = [{"role":"system","content":system_prompt},
            {"role":"user","content":user_prompt}]
    resp = ollama.chat(model=OLLAMA_MODEL, messages=msgs)
    return resp["message"]["content"]
