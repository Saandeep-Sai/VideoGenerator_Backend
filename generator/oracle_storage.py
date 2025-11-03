import oci
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class OracleStorageClient:
    def __init__(self):
        """Initialize Oracle Object Storage client"""
        try:
            # Read private key from file
            key_file_path = os.path.expanduser(os.getenv("ORACLE_KEY_FILE", "~/oracle-api-key.pem"))
            
            with open(key_file_path, 'r') as f:
                private_key = f.read()
            
            config = {
                "user": os.getenv("ORACLE_USER_OCID"),
                "key_content": private_key,
                "fingerprint": os.getenv("ORACLE_FINGERPRINT"),
                "tenancy": os.getenv("ORACLE_TENANCY_OCID"),
                "region": os.getenv("ORACLE_REGION", "us-phoenix-1")
            }
            
            self.object_storage = oci.object_storage.ObjectStorageClient(config)
            self.namespace = self.object_storage.get_namespace().data
            self.bucket_name = os.getenv("ORACLE_BUCKET_NAME", "video-generator-outputs")
            
            logger.info(f"✅ Oracle Object Storage initialized - Namespace: {self.namespace}, Bucket: {self.bucket_name}")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Oracle Storage: {e}")
            raise

    def upload_video(self, local_file_path: str, object_name: str = None) -> str:
        """
        Upload video file to Oracle Object Storage
        
        Args:
            local_file_path: Path to local video file
            object_name: Name for the object in bucket (optional, defaults to filename)
            
        Returns:
            Public URL of the uploaded video
        """
        try:
            if not object_name:
                object_name = Path(local_file_path).name
            
            # Read file
            with open(local_file_path, 'rb') as file:
                file_data = file.read()
            
            # Upload to Object Storage
            file_size_mb = len(file_data) / (1024 * 1024)
            logger.info(f"📤 Uploading {local_file_path} ({file_size_mb:.2f}MB) to Oracle Object Storage...")
            
            self.object_storage.put_object(
                namespace_name=self.namespace,
                bucket_name=self.bucket_name,
                object_name=object_name,
                put_object_body=file_data,
                content_type="video/mp4"
            )
            
            # Generate public URL
            region = os.getenv('ORACLE_REGION', 'us-phoenix-1')
            public_url = f"https://objectstorage.{region}.oraclecloud.com/n/{self.namespace}/b/{self.bucket_name}/o/{object_name}"
            
            logger.info(f"✅ Video uploaded successfully: {public_url}")
            
            return public_url
            
        except Exception as e:
            logger.error(f"❌ Failed to upload video: {e}")
            raise

    def delete_video(self, object_name: str) -> bool:
        """Delete video from Oracle Object Storage"""
        try:
            self.object_storage.delete_object(
                namespace_name=self.namespace,
                bucket_name=self.bucket_name,
                object_name=object_name
            )
            logger.info(f"🗑️ Deleted video: {object_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to delete video: {e}")
            return False

    def list_videos(self, prefix: str = None) -> list:
        """List all videos in bucket"""
        try:
            objects = self.object_storage.list_objects(
                namespace_name=self.namespace,
                bucket_name=self.bucket_name,
                prefix=prefix
            )
            return [obj.name for obj in objects.data.objects]
            
        except Exception as e:
            logger.error(f"❌ Failed to list videos: {e}")
            return []
