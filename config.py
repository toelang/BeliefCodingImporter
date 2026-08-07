"""
Central configuration for the Belief Coding Resource Importer.

Edit the values below to control what gets crawled, where it gets
uploaded to, and how source folders get organised in the destination.
Nothing outside this file should need to be touched for day-to-day use.
"""

from pathlib import Path

# --------------------------------------------------------------------------
# Project paths
# --------------------------------------------------------------------------

# Directory this file lives in - all other paths are resolved relative to it
# so the project can be run from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parent

# --------------------------------------------------------------------------
# Input: index PDFs
# --------------------------------------------------------------------------

# Folder containing the index PDFs you were sent (Pay in Full Bonuses,
# Pay Monthly Bonuses, Reiki 1, Reiki 2, 46 Day Launch Programme, etc).
#
# IMPORTANT: these PDFs are never uploaded to Google Drive. They are read
# only to extract the Google Drive links they contain. Place every index
# PDF you have into this folder before running the importer.
PDF_FOLDER = PROJECT_ROOT / "PDFs"

# --------------------------------------------------------------------------
# Output: destination Google Drive folder
# --------------------------------------------------------------------------

# This folder must already exist in your Google Drive. Every imported
# programme/file is placed inside it directly - the importer never
# creates an extra top-level "Belief Coding" wrapper folder of its own.
DESTINATION_FOLDER_URL = "https://drive.google.com/drive/folders/1IhfnUUiwlSjoYFUQqKqA3jOzaN8pXRmQ"

# --------------------------------------------------------------------------
# Additional Google Drive folders to crawl
# --------------------------------------------------------------------------

# Besides whatever is linked from inside the index PDFs, the importer will
# also crawl every folder/file URL listed here. Add more any time - the
# importer picks up new entries automatically on the next run.
ADDITIONAL_DRIVE_FOLDERS = [
    # 2 Weeks to £10K
    "https://drive.google.com/drive/folders/1olJEu_MES57iO8BislP3FO0Kyi_d5DKk",
]

# --------------------------------------------------------------------------
# Wrapper folders to flatten
# --------------------------------------------------------------------------

# Any Drive folder whose name contains one of these phrases (case
# insensitive) is treated as a transparent marketing/membership wrapper:
# its own name is NEVER recreated in the destination. The importer looks
# straight through it and processes its contents as if they sat one level
# further up. This is applied recursively, at any depth, and even if a
# link points directly at a wrapper folder.
WRAPPER_FOLDER_NAMES = [
    "pay monthly bonuses",
    "pay in full bonuses",
    "bonuses",
    "member resources",
    "shared resources",
]

# --------------------------------------------------------------------------
# Manual programme name overrides
# --------------------------------------------------------------------------

# Optional. If a source folder's name in Google Drive doesn't match what
# you want the destination folder to be called, add an entry here.
# Matching is case-insensitive and must be an exact match on the source
# folder's Drive name. Leave empty to keep source folder names as-is.
#
# Example:
#   PROGRAMME_RENAMES = {
#       "Reiki Level 1 - Member Area": "Reiki 1",
#   }
PROGRAMME_RENAMES = {}

# --------------------------------------------------------------------------
# Local working files (created automatically, safe to delete to start over)
# --------------------------------------------------------------------------

CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
TOKEN_FILE = PROJECT_ROOT / "token.json"
DATABASE_FILE = PROJECT_ROOT / "import_state.db"
LOG_CSV_FILE = PROJECT_ROOT / "import_log.csv"
DEBUG_LOG_FILE = PROJECT_ROOT / "debug.log"
TEMP_DIR = PROJECT_ROOT / "_temp_downloads"

# --------------------------------------------------------------------------
# Google API settings
# --------------------------------------------------------------------------

# Full Drive scope is required because we need to both read files shared
# with you (the source links) and write into your own destination folder.
SCOPES = ["https://www.googleapis.com/auth/drive"]

# Chunk size (bytes) used for resumable uploads/downloads of large files
# (e.g. videos). 10 MB is a safe default for most connections.
CHUNK_SIZE = 10 * 1024 * 1024

# How many times to retry a Drive API call after a transient error
# (rate limiting, network blip, 5xx) before giving up on that one file
# and logging it as an error.
MAX_RETRIES = 5

# Base delay (seconds) for exponential backoff between retries.
RETRY_BASE_DELAY = 2

# --------------------------------------------------------------------------
# Native Google Workspace files (Docs / Sheets / Slides / Drawings)
# --------------------------------------------------------------------------

# These have no raw binary content, so they can't be downloaded and
# re-uploaded as-is. The importer exports them to the format below,
# downloads that, then re-uploads with the original Workspace mime type
# so Drive automatically converts it back into a live, editable Doc/
# Sheet/Slide in your destination - the content is preserved, and no
# "Make a Copy" action or unwanted "Copy of ..." naming is ever used.
GOOGLE_NATIVE_EXPORTS = {
    "application/vnd.google-apps.document": {
        "export_mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "extension": ".docx",
    },
    "application/vnd.google-apps.spreadsheet": {
        "export_mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "extension": ".xlsx",
    },
    "application/vnd.google-apps.presentation": {
        "export_mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "extension": ".pptx",
    },
    "application/vnd.google-apps.drawing": {
        "export_mime": "image/png",
        "extension": ".png",
    },
}
