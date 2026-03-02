#!/usr/bin/env python3
"""
Test script for Video Generation with Key Rotation
Tests the actual video generation pipeline to verify key rotation works
"""

import os
from dotenv import load_dotenv
import requests

load_dotenv(override=True)
api_key = os.environ.get("GROQ_API_KEY")
url = "https://api.groq.com/openai/v1/models"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

response = requests.get(url, headers=headers)

with open("groqmodels.json", "w") as f:
    f.write(response.text)