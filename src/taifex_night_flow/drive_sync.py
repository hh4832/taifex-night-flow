"""Safe rclone-based Drive transport. The caller supplies an authenticated remote alias."""
from __future__ import annotations
import subprocess
from pathlib import Path
from .config import DRIVE_FOLDER_ID

class DriveSyncError(RuntimeError): pass

def sync_tree(local_root: str | Path, remote: str, folder_id: str = DRIVE_FOLDER_ID):
    if folder_id != DRIVE_FOLDER_ID: raise DriveSyncError("refusing unexpected Google Drive folder ID")
    root=Path(local_root)
    target=f"{remote}:"
    proc=subprocess.run(["rclone","copy",str(root),target,"--exclude",".state/**","--create-empty-src-dirs","--drive-root-folder-id",folder_id],capture_output=True,text=True)
    if proc.returncode:
        raise DriveSyncError(f"rclone copy failed (exit {proc.returncode}): {proc.stderr[-1000:]}")
    check=subprocess.run(["rclone","lsf",target,"--recursive","--drive-root-folder-id",folder_id],capture_output=True,text=True)
    if check.returncode: raise DriveSyncError("Drive post-upload verification failed")
    remote_files=set(check.stdout.splitlines())
    expected={p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".state" not in p.parts}
    missing=sorted(expected-remote_files)
    if missing: raise DriveSyncError(f"Drive verification is missing {len(missing)} file(s): {', '.join(missing[:5])}")
    return {"target":target,"folder_id":folder_id,"files":sorted(remote_files)}

def publish_latest(local_file: str | Path, remote: str, folder_id: str = DRIVE_FOLDER_ID):
    if folder_id != DRIVE_FOLDER_ID: raise DriveSyncError("refusing unexpected Google Drive folder ID")
    source=Path(local_file); target=f"{remote}:latest.json"
    options=["--drive-root-folder-id",folder_id]
    listing=subprocess.run(["rclone","lsf",f"{remote}:","--files-only",*options],capture_output=True,text=True)
    if listing.returncode: raise DriveSyncError("cannot inspect Drive before publishing latest.json")
    previous=None
    if "latest.json" in listing.stdout.splitlines():
        old=subprocess.run(["rclone","cat",target,*options],capture_output=True)
        if old.returncode: raise DriveSyncError("cannot back up existing Drive latest.json")
        previous=old.stdout
    uploaded=subprocess.run(["rclone","copyto",str(source),target,*options],capture_output=True,text=True)
    verified=subprocess.run(["rclone","cat",target,*options],capture_output=True)
    if uploaded.returncode or verified.returncode or verified.stdout!=source.read_bytes():
        # Best-effort rollback protects the previous pointer if the new write cannot be verified.
        if previous is None:
            subprocess.run(["rclone","deletefile",target,*options],capture_output=True)
        else:
            import tempfile
            with tempfile.NamedTemporaryFile() as backup:
                backup.write(previous); backup.flush()
                subprocess.run(["rclone","copyto",backup.name,target,*options],capture_output=True)
        raise DriveSyncError("latest pointer upload or read-back verification failed; previous pointer restore attempted")
    return target
