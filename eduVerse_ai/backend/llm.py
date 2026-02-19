"""
llm.py — Ollama LLM client for EduVerse AI

Works with qwen2.5:7b, llama3.1:8b, mistral:7b (any Ollama model).
No API key needed.
"""

import json
import os
import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# MODEL      = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
MODEL      = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")


SYSTEM_PROMPT = """You are EduVerse AI — a precise assistant for Lovely Professional University (LPU).

YOUR ONLY JOB: Answer questions using ONLY the text in the CONTEXT section below.

STRICT RULES:
1. If the CONTEXT contains the answer → give it clearly and completely.
2. If the CONTEXT is empty or does not contain the answer → say EXACTLY:
   "I don't have that information in the uploaded documents. Please visit 32 Block or ask your Head of department for the same."
3. NEVER invent, guess, or use general knowledge. NEVER say things like "typically" or "usually" unless quoting the document.
4. NEVER answer from timetable data when asked about scholarships or policies.
5. For scholarship questions: always include the process steps, window numbers, eligibility, and contact details if present.
6. For timetable questions: always include day, time, course code, section, room number.
7. Be direct. Use bullet points for steps/lists. Use tables for structured data.
8. If the user is writing appreciation or compliment like "hello", "hi", "hey", "good morning", "good afternoon", "good evening", "good night", "thank you", "thanks", "you are great", "you are amazing", "you are helpful", "you are intelligent", "you are smart", "you are kind", "you are nice", "you are friendly", "you are awesome", "you are wonderful", "you are fantastic", "you are brilliant", "you are excellent", "you are superb", always say responed in a good, nice and professional manner."""


def ask(query, context, history=None):
    """Send question + retrieved context to Ollama. Returns answer string."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in (history or [])[-6:]:
        messages.append(msg)

    if context:
        user_content = (
            f"CONTEXT (answer ONLY from this):\n\n{context}\n\n"
            f"{'─'*40}\n"
            f"QUESTION: {query}"
        )
    else:
        user_content = (
            f"CONTEXT: [No relevant documents found]\n\n"
            f"QUESTION: {query}\n\n"
            f"(Since no context was found, tell the user you don't have that information "
            f"and suggest uploading the relevant document.)"
        )

    messages.append({"role": "user", "content": user_content})

    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.05,    # very low — we want factual, not creative
            "num_predict": 1024,
            "top_p": 0.9,
        },
    }

    try:
        r = httpx.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except httpx.ConnectError:
        return "⚠️ Cannot connect to Ollama. Please run: `ollama serve`"
    except httpx.TimeoutException:
        return "⚠️ Ollama took too long. Try a smaller model or check your system resources."
    except Exception as e:
        return f"⚠️ LLM error: {e}"


async def ask_stream(query, context, history=None):
    """Streaming version — yields text tokens."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in (history or [])[-6:]:
        messages.append(msg)

    if context:
        user_content = f"CONTEXT:\n\n{context}\n\n{'─'*40}\nQUESTION: {query}"
    else:
        user_content = (
            f"CONTEXT: [No relevant documents found]\n\nQUESTION: {query}\n\n"
            f"Tell the user you don't have that information and suggest uploading the relevant document."
        )

    messages.append({"role": "user", "content": user_content})

    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": True,
        "options": {"temperature": 0.05, "num_predict": 1024},
    }

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if chunk.get("done"):
                            break
                    except Exception:
                        continue
        except httpx.ConnectError:
            yield "⚠️ Cannot connect to Ollama. Please run: `ollama serve`"


def health():
    try:
        r      = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        return {
            "ollama":          "online",
            "model":           MODEL,
            "model_available": any(MODEL in m for m in models),
            "all_models":      models,
        }
    except Exception as e:
        return {"ollama": "offline", "error": str(e)}