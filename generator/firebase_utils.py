import firebase_admin
from firebase_admin import credentials, firestore, storage
import os
import json
import base64
from dotenv import load_dotenv

load_dotenv()

def initialize_firebase():
    if firebase_admin._apps:
        return

    b64 = os.getenv("FIREBASE_CREDENTIALS_BASE64")
    project_id = os.getenv("FIREBASE_PROJECT_ID")
    if not b64 or not project_id:
        raise ValueError("Missing Firebase .env config")

    decoded = base64.b64decode(b64)
    cred_dict = json.loads(decoded.decode())
    cred = credentials.Certificate(cred_dict)

    firebase_admin.initialize_app(cred, {
        "projectId": project_id,
        "storageBucket": f"{project_id}.appspot.com"
    })
def save_base64_segments_to_firestore(base64_str: str, topic: str, duration: int):
    initialize_firebase()
    db = firestore.client()

    # Create master doc
    doc_ref = db.collection("videos").document()
    doc_ref.set({
        "topic": topic,
        "duration": duration,
        "segment_count": 0  # will update later
    })

    # Split base64 string
    segments = split_base64_string(base64_str)

    # Upload each segment as subcollection doc
    segment_coll = doc_ref.collection("video_segments")
    for i, (segment_id, content) in enumerate(segments.items(), start=1):
        segment_coll.document(segment_id).set({
            "segment_index": i,
            "content": content
        })

    # Update segment count
    doc_ref.update({"segment_count": len(segments)})

    return doc_ref.id

def split_base64_string(b64_string, segment_size=250000):
    return {
        f"segment_{i+1}": b64_string[i:i+segment_size]
        for i in range(0, len(b64_string), segment_size)
    }
