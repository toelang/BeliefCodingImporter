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
# Programme grouping for links with no containing Drive folder
# --------------------------------------------------------------------------
#
# Some PDFs link straight to dozens of individual files with no shared
# Drive folder holding them together - the relationship only exists in
# how the PDF lays them out, which Drive itself has no record of. Two
# mechanisms below recover that grouping. Both only apply to a link that
# would otherwise land unfoldered at the destination root (i.e. Drive
# folder structure, when it exists, always wins).
#
# 1. PDF_PROGRAMME_DEFAULTS: for a PDF that is entirely about ONE
#    programme (e.g. the whole "Reiki 1" PDF), every link found in it
#    defaults to that programme. Matching is done against the PDF's
#    filename with all non-letters/digits stripped and lowercased, so
#    "Belief Coding® Reiki 1 pdf.pdf" and "Belief_Coding__Reiki_1.pdf"
#    both match the key "reiki1". Add an entry here for any future
#    single-programme index PDF.
PDF_PROGRAMME_DEFAULTS = {
    "reiki1": "Reiki 1",
    "reiki2": "Reiki 2",
    "46daylaunchprogramme": "46 Day Launch Programme",
    "46daylaunch": "46 Day Launch Programme",
}

# 2. FILE_PROGRAMME_OVERRIDES: for bundle PDFs (Pay Monthly Bonuses, Pay
#    in Full Bonuses) that mix several distinct programmes together in
#    one document, a per-PDF default isn't safe - some of their sections
#    are genuinely one cohesive programme (Money Mindset, Confidence
#    Masterclass, ...) while others are a category heading loosely
#    grouping many unrelated one-off bonuses that should stay separate.
#    That distinction isn't reliably detectable from PDF layout alone, so
#    it's made explicit here instead, keyed by the exact original
#    filename as it appears in Drive (filenames are never renamed, so
#    this stays stable). Built directly from the discovered file list;
#    if a future run's plan shows something that should be grouped but
#    isn't (or vice versa), add/adjust an entry here and re-run the plan.
FILE_PROGRAMME_OVERRIDES = {
    # Money Mindset
    "Money Mindset - Module 1.mp4": "Money Mindset",
    "Money Mindset - Module 2.mp4": "Money Mindset",
    "Money Mindset - Module 3.mp4": "Money Mindset",
    "Money Mindset - Module 4.mp4": "Money Mindset",
    "Money Mindset - Module 5.mp4": "Money Mindset",
    "Money Mindset - Module 6.mp4": "Money Mindset",
    "Money Mindset - Module 7.mp4": "Money Mindset",
    "Money Mindset - Module 8.mp4": "Money Mindset",
    "Money_Mindset.pdf": "Money Mindset",
    # Business & Marketing Blueprint
    "Customer Avatar.mp4": "Business & Marketing Blueprint",
    "Business & Marketing Blueprint.mp4": "Business & Marketing Blueprint",
    "Tone of Voice.mp4": "Business & Marketing Blueprint",
    "Building Your Tribe.mp4": "Business & Marketing Blueprint",
    "Facebook® Groups.mp4": "Business & Marketing Blueprint",
    "Instagram®.mp4": "Business & Marketing Blueprint",
    "Facebook® Growth.mp4": "Business & Marketing Blueprint",
    "What Are You Selling.mp4": "Business & Marketing Blueprint",
    "Your Launch.mp4": "Business & Marketing Blueprint",
    "Launch Format.mp4": "Business & Marketing Blueprint",
    # Confidence Masterclass
    "Powering through to become CONFIDENT AF! The Masterclass.mp4": "Confidence Masterclass",
    "Increase Your Self Confidence & Self Esteem.mp4": "Confidence Masterclass",
    "Powering through to become CONFIDENT AF! Confidence!.mp4": "Confidence Masterclass",
    "Self_-_Confidence_and_Self_-_Esteem.pdf": "Confidence Masterclass",
    "COFIDENCE_11_STEPS.pdf": "Confidence Masterclass",
    "Confidence Coaching": "Confidence Masterclass",
    # Business Coaching Programme (6-week series + Business Day sessions + downloads)
    "Business Coaching - Week One - Alignment.mp4": "Business Coaching Programme",
    "Business Coaching - Week Two - Becoming Magnetic.mp4": "Business Coaching Programme",
    "Business Coaching - Week Three - Your Tribe.mp4": "Business Coaching Programme",
    "Business Coaching - Week Four - Planning a Launch.mp4": "Business Coaching Programme",
    "Business Coaching - Week Five - Passive Income Masterclass.mp4": "Business Coaching Programme",
    "Business Coaching - Week Six - Facebook® Ads.mp4": "Business Coaching Programme",
    "Business Day - Day 1 Replay.mp4": "Business Coaching Programme",
    "Business Day - Where Are You Now.mp4": "Business Coaching Programme",
    "Business Day - Your Goal.mp4": "Business Coaching Programme",
    "Business Day - Your Invincible Offer.mp4": "Business Coaching Programme",
    "Business Day - Your Launch.mp4": "Business Coaching Programme",
    "Business Day - Growing Your Audience.mp4": "Business Coaching Programme",
    "business_coaching.pdf": "Business Coaching Programme",
    "Business_Coaching_Week_3-_Your_Tribe.pdf": "Business Coaching Programme",
    "CFE_Social_Media_The_easy_way_INTERACTIVE_1_1_.pdf": "Business Coaching Programme",
    # Manifestation Coding
    "Manifestation_Coding.pdf": "Manifestation Coding",
    "Manifesting Coding.mp4": "Manifestation Coding",
}

# --------------------------------------------------------------------------
# Local working files (created automatically, safe to delete to start over)
# --------------------------------------------------------------------------

CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
TOKEN_FILE = PROJECT_ROOT / "token.json"
DATABASE_FILE = PROJECT_ROOT / "import_state.db"
LOG_CSV_FILE = PROJECT_ROOT / "import_log.csv"
PLAN_REPORT_FILE = PROJECT_ROOT / "import_plan.txt"
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
