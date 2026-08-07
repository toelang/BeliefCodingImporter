"""
Everything that talks to Google Drive on the "write" side: authentication,
creating destination folders, downloading a source file to a temp path,
and uploading it into the destination. Also used by drive_crawler.py for
its (read-only) API calls, since both need the same authenticated service
and the same retry/backoff behaviour.
"""

import io
import logging
import random
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

import config

log = logging.getLogger("belief_coding_importer.drive_uploader")

# HTTP status codes worth retrying - rate limiting and transient server errors.
_RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}
_RATE_LIMIT_REASONS = {"userRateLimitExceeded", "rateLimitExceeded"}


class InaccessibleError(Exception):
    """Raised when a Drive resource is genuinely not accessible (404/403
    that isn't just rate limiting) - i.e. a broken or permission-denied link."""


def _escape_query_value(value: str) -> str:
    """Escape a value for safe use inside a single-quoted Drive API query string."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def get_drive_service():
    """Authenticate via the OAuth Desktop flow, reusing a cached token
    where possible, and return a ready-to-use Drive v3 service object."""
    creds = None
    if config.TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(config.TOKEN_FILE), config.SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Refreshing expired Google auth token...")
            creds.refresh(Request())
        else:
            if not config.CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"'{config.CREDENTIALS_FILE.name}' not found in {config.PROJECT_ROOT}.\n"
                    "Download an OAuth 'Desktop app' client secret from Google Cloud Console "
                    "and save it there (see README.md)."
                )
            log.info("No valid token found - opening browser for Google sign-in...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(config.CREDENTIALS_FILE), config.SCOPES
            )
            creds = flow.run_local_server(port=0)
        config.TOKEN_FILE.write_text(creds.to_json())
        log.info("Saved auth token to %s for future runs.", config.TOKEN_FILE.name)

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def with_retry(description, func, *args, **kwargs):
    """Call func(*args, **kwargs), retrying on transient Drive API errors
    with exponential backoff + jitter. Raises InaccessibleError immediately
    for genuine 404/permission-denied responses (no point retrying those)."""
    last_exc = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except HttpError as exc:
            status = exc.resp.status if exc.resp is not None else None
            reason = ""
            try:
                reason = exc.error_details[0].get("reason", "") if exc.error_details else ""
            except Exception:
                pass

            if status == 404:
                raise InaccessibleError(f"{description}: not found (404)") from exc
            if status == 403 and reason not in _RATE_LIMIT_REASONS:
                raise InaccessibleError(f"{description}: permission denied (403)") from exc
            if status not in _RETRYABLE_STATUS:
                raise

            last_exc = exc
            delay = config.RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 1)
            log.warning(
                "%s failed (attempt %d/%d, status %s) - retrying in %.1fs",
                description, attempt, config.MAX_RETRIES, status, delay,
            )
            time.sleep(delay)
        except (ConnectionError, TimeoutError, OSError) as exc:
            last_exc = exc
            delay = config.RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 1)
            log.warning(
                "%s failed (attempt %d/%d, network error: %s) - retrying in %.1fs",
                description, attempt, config.MAX_RETRIES, exc, delay,
            )
            time.sleep(delay)

    raise RuntimeError(f"{description}: giving up after {config.MAX_RETRIES} attempts") from last_exc


# --------------------------------------------------------------------------
# Folder management
# --------------------------------------------------------------------------

def resolve_folder_id_from_url(url: str) -> str:
    from pdf_parser import parse_drive_url
    parsed = parse_drive_url(url)
    if not parsed:
        raise ValueError(f"Not a recognisable Google Drive URL: {url}")
    return parsed[1]


def ensure_folder(service, db, parent_id: str, name: str) -> str:
    """Get-or-create a destination folder named `name` under `parent_id`,
    memoised in the database so repeated runs never create duplicates."""
    cached = db.get_dest_folder(parent_id, name)
    if cached:
        return cached

    escaped_name = _escape_query_value(name)
    query = (
        f"'{parent_id}' in parents and name = '{escaped_name}' "
        "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )

    def _search():
        return service.files().list(
            q=query,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

    result = with_retry(f"search for folder '{name}'", _search)
    existing = result.get("files", [])
    if existing:
        folder_id = existing[0]["id"]
    else:
        def _create():
            return service.files().create(
                body={
                    "name": name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [parent_id],
                },
                fields="id",
                supportsAllDrives=True,
            ).execute()

        created = with_retry(f"create folder '{name}'", _create)
        folder_id = created["id"]
        log.info("Created destination folder: %s", name)

    db.set_dest_folder(parent_id, name, folder_id)
    return folder_id


def ensure_path(service, db, root_id: str, path_segments) -> str:
    """Get-or-create each segment of a nested path under root_id, returning
    the id of the final (deepest) folder. Empty segments are skipped."""
    current = root_id
    for segment in path_segments:
        if not segment:
            continue
        current = ensure_folder(service, db, current, segment)
    return current


# --------------------------------------------------------------------------
# Existing-file check in the destination (safety net beyond the local DB)
# --------------------------------------------------------------------------

def find_existing_in_destination(service, parent_id: str, name: str, size):
    """Defensive check against the live destination folder, in case the
    local database was lost/reset but the file was already uploaded."""
    escaped_name = _escape_query_value(name)
    query = f"'{parent_id}' in parents and name = '{escaped_name}' and trashed = false"

    def _search():
        return service.files().list(
            q=query,
            fields="files(id, name, size, md5Checksum)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

    result = with_retry(f"check existing file '{name}'", _search)
    for f in result.get("files", []):
        existing_size = f.get("size")
        if size is None or existing_size is None or str(existing_size) == str(size):
            return f
    return None


# --------------------------------------------------------------------------
# Download (source -> local temp file)
# --------------------------------------------------------------------------

def download_binary(service, file_id: str, dest_path: Path):
    """Download a regular (binary) Drive file to dest_path."""
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    _stream_download(request, dest_path)


def download_export(service, file_id: str, export_mime: str, dest_path: Path):
    """Export a native Google Workspace file (Doc/Sheet/Slide/Drawing) to
    a static format we can re-upload."""
    request = service.files().export_media(fileId=file_id, mimeType=export_mime)
    _stream_download(request, dest_path)


def _stream_download(request, dest_path: Path):
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.FileIO(str(dest_path), "wb")
    try:
        downloader = MediaIoBaseDownload(buffer, request, chunksize=config.CHUNK_SIZE)
        done = False
        while not done:
            def _next_chunk():
                return downloader.next_chunk()
            _, done = with_retry(f"download to {dest_path.name}", _next_chunk)
    finally:
        buffer.close()


# --------------------------------------------------------------------------
# Upload (local temp file -> destination)
# --------------------------------------------------------------------------

def upload_binary(service, local_path: Path, name: str, parent_id: str, mime_type: str = None) -> dict:
    """Upload a local file as a plain binary file into parent_id."""
    media = MediaFileUpload(str(local_path), mimetype=mime_type, chunksize=config.CHUNK_SIZE, resumable=True)
    body = {"name": name, "parents": [parent_id]}

    def _create():
        request = service.files().create(
            body=body,
            media_body=media,
            fields="id, name, size, md5Checksum, sha256Checksum",
            supportsAllDrives=True,
        )
        response = None
        while response is None:
            status, response = request.next_chunk()
        return response

    return with_retry(f"upload '{name}'", _create)


def upload_as_native(service, local_path: Path, name: str, parent_id: str, workspace_mime: str) -> dict:
    """Upload a local (e.g. .docx) file but ask Drive to convert it into a
    live native Google Doc/Sheet/Slide with the given mime type, restoring
    the original file's editability in the destination."""
    media = MediaFileUpload(str(local_path), mimetype=_office_mime_for(workspace_mime), resumable=True)
    body = {"name": name, "parents": [parent_id], "mimeType": workspace_mime}

    def _create():
        request = service.files().create(
            body=body,
            media_body=media,
            fields="id, name, size, md5Checksum, sha256Checksum",
            supportsAllDrives=True,
        )
        response = None
        while response is None:
            status, response = request.next_chunk()
        return response

    return with_retry(f"upload (native) '{name}'", _create)


def _office_mime_for(workspace_mime: str) -> str:
    exports = config.GOOGLE_NATIVE_EXPORTS[workspace_mime]
    return exports["export_mime"]


def get_file_metadata(service, file_id: str, fields: str = None) -> dict:
    fields = fields or (
        "id, name, mimeType, size, md5Checksum, sha256Checksum, trashed, "
        "shortcutDetails, parents"
    )

    def _get():
        return service.files().get(
            fileId=file_id, fields=fields, supportsAllDrives=True
        ).execute()

    return with_retry(f"get metadata for {file_id}", _get)


def list_children(service, folder_id: str):
    """Yield every non-trashed child of folder_id, transparently paging."""
    page_token = None
    while True:
        def _list():
            return service.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields=(
                    "nextPageToken, files(id, name, mimeType, size, md5Checksum, "
                    "sha256Checksum, shortcutDetails)"
                ),
                pageSize=200,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()

        result = with_retry(f"list children of {folder_id}", _list)
        for f in result.get("files", []):
            yield f
        page_token = result.get("nextPageToken")
        if not page_token:
            break
