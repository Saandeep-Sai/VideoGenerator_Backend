import firebase_admin
from firebase_admin import credentials, firestore
import os
import json
import base64
from dotenv import load_dotenv

load_dotenv()

# Initialize Firebase app
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

# Save a new Firestore document with status 'processing'
def save_base64_segments_to_firestore(base64_str: str, topic: str, duration: int, status="processing"):
    initialize_firebase()
    db = firestore.client()

    doc_ref = db.collection("videos").document()
    doc_ref.set({
        "topic": topic,
        "duration": duration,
        "status": status,
        "segment_count": 0,
        "created_at": firestore.SERVER_TIMESTAMP
    })

    # If base64 provided, upload it
    if base64_str:
        segments = split_base64_string(base64_str)
        segment_coll = doc_ref.collection("video_segments")
        for i, (segment_id, content) in enumerate(segments.items(), start=1):
            segment_coll.document(segment_id).set({
                "segment_index": i,
                "content": content
            })

        doc_ref.update({
            "segment_count": len(segments)
        })

    return doc_ref.id

# Update an existing video doc with completion and optionally upload base64
def update_video_status(doc_id, base64_data=None, status="completed", error=None):
    initialize_firebase()
    db = firestore.client()
    doc_ref = db.collection("videos").document(doc_id)

    update_fields = {
        "status": status
    }
    if error:
        update_fields["error"] = error

    doc_ref.update(update_fields)

    if base64_data:
        segments = split_base64_string(base64_data)
        segment_coll = doc_ref.collection("video_segments")
        for i, (segment_id, content) in enumerate(segments.items(), start=1):
            segment_coll.document(segment_id).set({
                "segment_index": i,
                "content": content
            })
        doc_ref.update({"segment_count": len(segments)})

# Helper: split long base64 into smaller segments
def split_base64_string(b64_string, segment_size=950000):  # just under 1MB limit
    return {
        f"segment_{i+1}": b64_string[i:i+segment_size]
        for i in range(0, len(b64_string), segment_size)
    }
# Create a new job in Firestore with 'pending' status
def create_job(topic, duration):
    initialize_firebase()
    db = firestore.client()

    doc_ref = db.collection("videos").document()
    doc_ref.set({
        "topic": topic,
        "duration": duration,
        "status": "pending",
        "created_at": firestore.SERVER_TIMESTAMP
    })
    return doc_ref.id

# Fetch one pending job from Firestore
def get_pending_jobs():
    import logging
    logger = logging.getLogger(__name__)
    
    initialize_firebase()
    db = firestore.client()

    # Debug: Log all videos to see what's actually in Firebase
    all_videos = db.collection("videos").limit(5).stream()
    logger.info("🔍 DEBUG: All recent videos in Firebase:")
    for v in all_videos:
        vdata = v.to_dict()
        logger.info(f"  - ID: {v.id}, Status: {vdata.get('status')}, Topic: {vdata.get('topic')}")

    jobs = db.collection("videos").where("status", "==", "pending").limit(1).stream()

    for doc in jobs:
        data = doc.to_dict()
        data["id"] = doc.id
        logger.info(f"✅ Found pending job: {doc.id}")
        return data
    
    logger.info("❌ No pending jobs found")
    return None

# Update status of an existing job
def update_job_status(doc_id, status):
    initialize_firebase()
    db = firestore.client()
    db.collection("videos").document(doc_id).update({"status": status})

# Add this to the bottom of your firebase_utils.py

# Get job by ID
def get_job_by_id(doc_id):
    initialize_firebase()
    db = firestore.client()
    doc = db.collection("videos").document(doc_id).get()
    if doc.exists:
        data = doc.to_dict()
        data["id"] = doc.id
        return data
    return None
