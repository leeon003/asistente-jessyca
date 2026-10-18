import os
import shutil
import hashlib
import json
from datetime import datetime

def hash_file(filepath):
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def backup_phase7():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = f"backups/fase7_pre_consolidation_{timestamp}"
    os.makedirs(backup_dir, exist_ok=True)
    
    manifest = {
        "timestamp": timestamp,
        "phase": "FASE 7 — CONSOLIDACION Y ENTREGA",
        "branch": "feature/jessyca-brain-1.0",
        "backed_up_items": []
    }
    
    # 1. Backup data directory (DBs and memories)
    if os.path.exists("data"):
        data_dest = os.path.join(backup_dir, "data")
        shutil.copytree("data", data_dest, dirs_exist_ok=True)
        for root, _, files in os.walk(data_dest):
            for file in files:
                rel = os.path.relpath(os.path.join(root, file), backup_dir)
                orig = os.path.join("data", os.path.relpath(os.path.join(root, file), data_dest))
                if os.path.exists(orig):
                    manifest["backed_up_items"].append({
                        "file": orig,
                        "backup_path": rel,
                        "sha256": hash_file(orig),
                        "size_bytes": os.path.getsize(orig)
                    })

    # 2. Backup config directory
    if os.path.exists("config"):
        cfg_dest = os.path.join(backup_dir, "config")
        shutil.copytree("config", cfg_dest, dirs_exist_ok=True)
        for root, _, files in os.walk(cfg_dest):
            for file in files:
                rel = os.path.relpath(os.path.join(root, file), backup_dir)
                orig = os.path.join("config", os.path.relpath(os.path.join(root, file), cfg_dest))
                if os.path.exists(orig):
                    manifest["backed_up_items"].append({
                        "file": orig,
                        "backup_path": rel,
                        "sha256": hash_file(orig),
                        "size_bytes": os.path.getsize(orig)
                    })

    # 3. Save manifest
    manifest_path = os.path.join(backup_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        
    print(f"BACKUP_COMPLETED: {backup_dir} ({len(manifest['backed_up_items'])} files backed up)")

if __name__ == "__main__":
    backup_phase7()
