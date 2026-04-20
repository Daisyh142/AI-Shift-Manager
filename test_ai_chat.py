#!/usr/bin/env python3
"""Quick test that Gemini is used for AI chat. Run with backend up: python3 test_ai_chat.py"""

import requests

BASE = "http://127.0.0.1:8000"

def run_ai_chat_smoke() -> None:
    # Seed and get owner token
    r = requests.post(f"{BASE}/seed", timeout=10)
    r.raise_for_status()

    r = requests.post(f"{BASE}/auth/login", json={"email": "owner@demo.com", "password": "demo"}, timeout=10)
    r.raise_for_status()
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Call AI chat
    r = requests.post(
        f"{BASE}/ai/chat",
        headers=headers,
        json={"message": "In one sentence, what should I focus on first with this schedule?"},
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()

    print("Response from /ai/chat:")
    print("-" * 60)
    print(data.get("assistant_message", "")[:500])
    print("-" * 60)
    if "Generate and review" in data.get("assistant_message", "") or "I cannot see a generated schedule" in data.get("assistant_message", ""):
        print("no Gemini key or key invalid.)")
    else:
        print("key is working.)")


if __name__ == "__main__":
    run_ai_chat_smoke()
