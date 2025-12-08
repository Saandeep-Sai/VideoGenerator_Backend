#!/usr/bin/env python3
"""
Diagnostic script to check youtube_shorts_history.json file
Run this on the server to verify file permissions and location
"""

import os
import json
from pathlib import Path
from datetime import datetime

def main():
    print("=" * 70)
    print("🔍 YOUTUBE SHORTS HISTORY FILE DIAGNOSTIC")
    print("=" * 70)
    print()
    
    # Check script directory
    script_dir = Path(__file__).parent
    print(f"📂 Script directory: {script_dir}")
    print(f"📂 Absolute path: {script_dir.absolute()}")
    print()
    
    # Check current working directory
    cwd = Path.cwd()
    print(f"📂 Current working directory: {cwd}")
    print()
    
    # History file paths to check
    history_files = [
        script_dir / "youtube_shorts_history.json",
        cwd / "youtube_shorts_history.json",
        Path("youtube_shorts_history.json"),
        Path("/home/ubuntu/VideoGenerator_Backend/youtube_shorts_history.json"),
    ]
    
    print("🔍 Checking possible history file locations...")
    print()
    
    for i, file_path in enumerate(history_files, 1):
        print(f"{i}. {file_path}")
        abs_path = file_path.absolute()
        print(f"   Absolute: {abs_path}")
        
        if file_path.exists():
            print(f"   ✅ EXISTS")
            
            # Check permissions
            stat_info = os.stat(file_path)
            print(f"   📊 Size: {stat_info.st_size} bytes")
            print(f"   🔐 Permissions: {oct(stat_info.st_mode)[-3:]}")
            print(f"   👤 Owner UID: {stat_info.st_uid}")
            print(f"   👥 Group GID: {stat_info.st_gid}")
            
            # Check if readable
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)
                print(f"   ✅ READABLE")
                print(f"   📊 Topics in file: {len(data)}")
                
                if data:
                    print(f"   📋 Sample topics:")
                    for topic, timestamp in list(data.items())[:3]:
                        print(f"      - {topic[:50]}... ({timestamp})")
            except PermissionError:
                print(f"   ❌ PERMISSION DENIED - Cannot read")
            except json.JSONDecodeError:
                print(f"   ❌ CORRUPTED - Invalid JSON")
            except Exception as e:
                print(f"   ❌ ERROR: {e}")
            
            # Check if writable
            try:
                test_data = data.copy() if 'data' in locals() else {}
                test_data["_test_write_" + datetime.now().isoformat()] = "test"
                with open(file_path, "w") as f:
                    json.dump(test_data, f, indent=2)
                print(f"   ✅ WRITABLE")
                
                # Remove test entry
                del test_data["_test_write_" + datetime.now().isoformat()]
                if 'data' in locals():
                    with open(file_path, "w") as f:
                        json.dump(data, f, indent=2)
            except PermissionError:
                print(f"   ❌ PERMISSION DENIED - Cannot write")
            except Exception as e:
                print(f"   ❌ WRITE ERROR: {e}")
        else:
            print(f"   ❌ DOES NOT EXIST")
            
            # Check if parent directory exists and is writable
            parent = file_path.parent
            if parent.exists():
                print(f"   📂 Parent directory exists: {parent}")
                try:
                    # Try to create the file
                    with open(file_path, "w") as f:
                        json.dump({}, f)
                    print(f"   ✅ CAN CREATE FILE (created empty file)")
                    # Clean up
                    file_path.unlink()
                except PermissionError:
                    print(f"   ❌ CANNOT CREATE - Permission denied")
                except Exception as e:
                    print(f"   ❌ CANNOT CREATE - {e}")
            else:
                print(f"   ❌ Parent directory does not exist: {parent}")
        
        print()
    
    print("=" * 70)
    print("📋 RECOMMENDATIONS")
    print("=" * 70)
    print()
    
    expected_path = script_dir / "youtube_shorts_history.json"
    print(f"✅ Expected location: {expected_path}")
    print()
    
    if not expected_path.exists():
        print("⚠️  File doesn't exist at expected location")
        print("💡 Run the scheduler once to create it:")
        print("   sudo systemctl start youtube-shorts-scheduler.service")
        print()
    
    print("📋 To check service logs:")
    print("   sudo journalctl -u youtube-shorts-scheduler.service -n 100 --no-pager")
    print()
    
    print("📋 To monitor in real-time:")
    print("   sudo journalctl -u youtube-shorts-scheduler.service -f")
    print()
    
    print("📋 To check file after service runs:")
    print(f"   cat {expected_path}")
    print()

if __name__ == "__main__":
    main()
