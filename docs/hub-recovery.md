# Encrypted hub recovery

This runbook applies to the Obsidian/Basic Memory hub. `recovery.md` describes the
separate legacy SQLite implementation; do not use its procedures on the vault.

## Key and destination

- Cloud folder: **Local Memory Backups** in the user's private Google Drive.
- Default encrypted outbox: `.runtime/drive-outbox/`.
- Recovery key: `.runtime/recovery-key.txt`, readable only by this user (0600).
- Private upload/restore evidence: `.runtime/drive-backup-receipt.json`.

Save the key in a password manager that can be recovered without this Mac. Do not
put it in the Drive backup folder or commit it. Without the key the archive cannot
be decrypted. The key has not been copied off the Mac by this setup.

The existing daily job creates local snapshots with 14-snapshot retention. Drive
currently contains a separately uploaded, verified encrypted snapshot. The user selected manual Drive uploads. No Drive desktop installation or unattended
uploader is configured; connected-chat tools alone are not a scheduled backup service.

## Create and upload

```sh
.venv/bin/python scripts/encrypted_backup.py create
```

Upload only the returned `.fernet` file to the private folder. Keep multiple dated
snapshots. Do not sync the live vault or the runtime directory. Check successful
upload, download the artifact, compare its SHA-256 with the creation output and run
the quarantined restore below. A sync client's local copy is not proof of cloud
durability. The create command does not upload anything.

## Restore to quarantine

Use a trusted checkout with `uv sync --locked`, the downloaded archive, and the
separately recovered key (0600). Never place the key in the vault.

```sh
.venv/bin/python scripts/encrypted_backup.py restore \
  --archive /absolute/downloaded-backup.fernet \
  --key /absolute/private/recovery-key.txt \
  --quarantine /absolute/existing-parent/new-review-directory
.venv/bin/python scripts/audit_memory_restore.py \
  --quarantine /absolute/existing-parent/new-review-directory/hub \
  --current-control /absolute/current/skill-memory \
  --current-general /absolute/current/general-memory \
  --current-vault /absolute/current/vault
```

Restore authenticates the encrypted envelope, verifies member hashes and checks the
hub/fitness archive formats. It creates `hub/vault`, control directories and a
separate fitness-owner quarantine, never an active installation. Existing quarantine
paths are refused. `recovery-tools.zip` contains a code/dependency snapshot, not
credentials or an automatically executed installer.

Before promotion, preserve the newest live skill forgetting ledger and general
capture receipts, including `general-memory/activity/receipts`. The same read-only
audit covers both general captures and activity events. Compare restored paths/hashes against the newest receipts
and files: missing or changed files can represent intentional deletion/editing.
Do not replace newer controls with historical controls or replay old requests to
recreate deleted notes. The read-only audit compares receipt-managed captures when both current general
paths are supplied. It reports missing/edited files, pending or changed receipts,
and captures newer than the snapshot. Native/manual notes without receipts still
require separate review. Revalidate owner sources, current configuration, review
dates and fitness ownership. If no newer controls survived, historical deletions
cannot be inferred reliably; review every proposed restored scope.

Promote only after that review, restore fitness via its owner runbook, reindex into
fresh Basic Memory state, and verify reads from both clients before resuming capture.

## If the checkout was lost

Prefer recovering the repository from its trusted Git source. As a fallback, the
authenticated bundle includes recovery source. On a clean machine, install Python
and `cryptography==50.0.1` from the standard package registry in a new virtual
environment. The following authenticates the archive and extracts only the source
ZIP into a new file; inspect it before extracting or executing any code:

```python
from pathlib import Path
from cryptography.fernet import Fernet
import hashlib, io, json, zipfile

clear = Fernet(Path("/private/recovery-key.txt").read_bytes().strip()).decrypt(
    Path("/downloads/backup.fernet").read_bytes())
with zipfile.ZipFile(io.BytesIO(clear)) as bundle:
    manifest = json.loads(bundle.read("manifest.json"))
    assert manifest["format"] == "local-memory-encrypted-recovery-v1"
    raw = bundle.read("recovery-tools.zip")
    assert manifest["files"]["recovery-tools.zip"] == {
        "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    with open("recovery-tools.zip", "xb") as target:
        target.write(raw)
```

## Verified rehearsal

On 2026-09-19 (America/Chicago), the encrypted Drive download matched its creation
SHA-256 and restored 132 hub files and 62 fitness records into a new local quarantine.
No restored state was activated. Wrong-key and modified-ciphertext rejection are
covered by synthetic tests. This verifies the tested snapshot, not future scheduled
runs, independent key storage, or a physical disk-loss event.
