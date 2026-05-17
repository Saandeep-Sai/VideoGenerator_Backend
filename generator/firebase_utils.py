import firebase_admin
from firebase_admin import credentials, firestore
import os
import json
import base64
from dotenv import load_dotenv

load_dotenv(override=True)

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

# DEPRECATED: Use create_job instead to avoid Firebase duplicates
def save_base64_segments_to_firestore(base64_str: str, topic: str, duration: int, status="processing"):
    import logging
    logger = logging.getLogger(__name__)
    
    logger.warning(f"⚠️ DEPRECATED: save_base64_segments_to_firestore called")
    logger.warning(f"⚠️ Use create_job + Oracle Storage instead to avoid duplicates")
    
    initialize_firebase()
    db = firestore.client()

    doc_ref = db.collection("videos").document()
    doc_ref.set({
        "topic": topic,
        "duration": duration,
        "status": status,
        "segment_count": 0,
        "storage_method": "firebase_base64_deprecated",
        "created_at": firestore.SERVER_TIMESTAMP
    })

    # SKIP base64 upload to prevent duplicates
    if base64_str:
        logger.warning(f"⚠️ SKIPPING base64 upload to prevent duplicates")
        logger.warning(f"⚠️ Base64 data size: {len(base64_str)} chars (not uploaded)")
        logger.warning(f"⚠️ Use Oracle Storage for video files instead")

    return doc_ref.id

# DEPRECATED: Use update_video_status_with_url instead to avoid Firebase duplicates
def update_video_status(doc_id, base64_data=None, status="completed", error=None):
    import logging
    logger = logging.getLogger(__name__)
    
    logger.warning(f"⚠️ DEPRECATED: update_video_status called for {doc_id}")
    logger.warning(f"⚠️ Use update_video_status_with_url instead to avoid Firebase duplicates")
    
    initialize_firebase()
    db = firestore.client()
    doc_ref = db.collection("videos").document(doc_id)

    update_fields = {
        "status": status,
        "updated_at": firestore.SERVER_TIMESTAMP,
        "storage_method": "firebase_base64_deprecated"
    }
    if error:
        update_fields["error"] = error

    doc_ref.update(update_fields)
    logger.info(f"✅ Updated job {doc_id} status to: {status}")

    # SKIP base64 upload to prevent duplicates
    if base64_data:
        logger.warning(f"⚠️ SKIPPING base64 upload to prevent duplicates - use Oracle Storage instead")
        logger.warning(f"⚠️ Base64 data size: {len(base64_data)} chars (not uploaded)")

# Update job status with video URL (for Oracle Object Storage) - SINGLE UPDATE, NO DUPLICATES
def update_video_status_with_url(doc_id, video_url, status="completed", error=None, youtube_video_id=None):
    import logging
    logger = logging.getLogger(__name__)
    
    initialize_firebase()
    db = firestore.client()
    doc_ref = db.collection("videos").document(doc_id)

    update_fields = {
        "status": status,
        "video_url": video_url,
        "updated_at": firestore.SERVER_TIMESTAMP
    }
    
    # Add YouTube video ID if provided (for uploaded shorts)
    if youtube_video_id:
        update_fields["youtube_video_id"] = youtube_video_id
        update_fields["youtube_url"] = f"https://youtube.com/watch?v={youtube_video_id}"
        update_fields["platform"] = "youtube_short"
    else:
        update_fields["platform"] = "oracle_storage"
    
    if error:
        update_fields["error"] = error

    # SINGLE UPDATE - no base64 video data, just metadata
    doc_ref.update(update_fields)
    logger.info(f"✅ Updated job {doc_id} status to: {status}")
    logger.info(f"📹 Video URL: {video_url}")
    if youtube_video_id:
        logger.info(f"📺 YouTube: https://youtube.com/watch?v={youtube_video_id}")
    logger.info(f"🚫 NO duplicate Firebase upload - using Oracle Storage + YouTube only")

# Helper: split long base64 into smaller segments
def split_base64_string(b64_string, segment_size=950000):  # just under 1MB limit
    return {
        f"segment_{i+1}": b64_string[i:i+segment_size]
        for i in range(0, len(b64_string), segment_size)
    }

# Create a new job in Firestore with 'pending' status (for API/manual requests)
def create_job(topic, duration, aspect_ratio="9:16", video_type="short", use_quality_pipeline=True):
    initialize_firebase()
    db = firestore.client()

    doc_ref = db.collection("videos").document()
    doc_ref.set({
        "topic": topic,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "video_type": video_type,
        "use_quality_pipeline": use_quality_pipeline,
        "status": "pending",
        "created_at": firestore.SERVER_TIMESTAMP,
        "source": "manual_api"
    })
    return doc_ref.id

# Create a scheduled job record (SEPARATE COLLECTION - won't be picked up by workers)
def create_scheduled_job(topic, duration, aspect_ratio="9:16", video_type="short"):
    """
    Create a job record in the 'scheduled-videos' collection.
    This collection is SEPARATE from 'videos' so workers won't pick it up.
    Used only for scheduler-generated videos to avoid double generation.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    initialize_firebase()
    db = firestore.client()

    doc_ref = db.collection("scheduled-videos").document()
    doc_ref.set({
        "topic": topic,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "video_type": video_type,
        "status": "processing",  # Start as processing (scheduler is generating)
        "created_at": firestore.SERVER_TIMESTAMP,
        "source": "automated_scheduler"
    })
    
    logger.info(f"📝 Created scheduled job in separate collection: {doc_ref.id}")
    return doc_ref.id

# Update scheduled job status (uses 'scheduled-videos' collection)
def update_scheduled_job_status(doc_id, video_url, status="completed", error=None, youtube_video_id=None):
    """
    Update a scheduled job in the 'scheduled-videos' collection.
    Separate from regular jobs to prevent worker pickup.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    initialize_firebase()
    db = firestore.client()
    doc_ref = db.collection("scheduled-videos").document(doc_id)

    update_fields = {
        "status": status,
        "video_url": video_url,
        "updated_at": firestore.SERVER_TIMESTAMP
    }
    
    # Add YouTube video ID if provided
    if youtube_video_id:
        update_fields["youtube_video_id"] = youtube_video_id
        update_fields["youtube_url"] = f"https://youtube.com/watch?v={youtube_video_id}"
        update_fields["platform"] = "youtube_short"
    else:
        update_fields["platform"] = "oracle_storage"
    
    if error:
        update_fields["error"] = error

    # Update in separate collection
    doc_ref.update(update_fields)
    logger.info(f"✅ Updated scheduled job {doc_id} status to: {status}")
    logger.info(f"📹 Video URL: {video_url}")
    if youtube_video_id:
        logger.info(f"📺 YouTube: https://youtube.com/watch?v={youtube_video_id}")
    logger.info(f"🔒 Stored in 'scheduled-videos' collection (won't be picked up by workers)")


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
