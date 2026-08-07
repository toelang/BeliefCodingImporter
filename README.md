# Belief Coding Resource Importer

A one-off migration tool that reads a folder of index PDFs, extracts every
Google Drive link they contain, crawls those links (and any additional
Drive folders you list) recursively, and uploads every discovered file
into your own Google Drive - organised by programme, with marketing
wrapper folders stripped out and duplicates never re-imported.

## What it does

1. Reads every PDF in `PDFs/` and extracts the real Google Drive links
   behind each clickable title (the PDFs themselves are **never**
   uploaded - they exist only to point at the real content).
2. Crawls every link found, plus anything listed in
   `config.ADDITIONAL_DRIVE_FOLDERS`, following folders inside folders
   until there is nothing left to discover.
3. Flattens marketing/membership wrapper folders (`Pay Monthly Bonuses`,
   `Pay in Full Bonuses`, `Bonuses`, `Member Resources`, `Shared
   Resources`) so they never appear in your Drive - only real programme
   content does.
4. Uploads everything into the destination folder you already have in
   Google Drive, grouping multi-file programmes into their own folder and
   placing single-file bonuses directly at the top level.
5. Skips anything it has already imported (by Drive file ID, then content
   hash, then filename+size), so re-running the tool after an
   interruption picks up exactly where it left off.
6. Logs everything to `import_log.csv` and prints live progress while it
   runs.

## Requirements

- Python 3.9 or later, installed and on your PATH.
- A Google account with access to the source links and to the
  destination Drive folder.
- An OAuth 2.0 **Desktop app** client from Google Cloud Console (see
  below) - this is a one-time setup step.

## 1. Get a `credentials.json`

The importer authenticates as *you*, using Google's standard OAuth
Desktop flow - it never has any credentials of its own baked in.

1. Go to <https://console.cloud.google.com/> and create a project (or
   pick an existing one).
2. **APIs & Services -> Library**: search for "Google Drive API" and
   click **Enable**.
3. **APIs & Services -> OAuth consent screen**: choose **External**,
   fill in an app name and your email address, and add yourself as a
   test user. You don't need to submit it for verification - it's fine
   to leave it in "Testing" mode for personal use.
4. **APIs & Services -> Credentials -> Create Credentials -> OAuth
   client ID**. Choose **Application type: Desktop app**, give it any
   name, and click **Create**.
5. Click **Download JSON** on the client you just created, rename the
   downloaded file to `credentials.json`, and place it in this project
   folder (next to `main.py`).

`credentials.json` and the `token.json` it later creates both contain
sensitive access to your Google account - they are excluded from git via
`.gitignore` and should never be shared or committed.

## 2. Install dependencies

Double-click `run.bat` - it creates a virtual environment in `venv/` and
installs everything from `requirements.txt` automatically on first run.

To do it manually instead:

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Add your input

- Put every index PDF you have into the `PDFs/` folder.
- Open `config.py` and check:
  - `DESTINATION_FOLDER_URL` - the existing Drive folder everything gets
    imported into (already set to the folder you gave).
  - `ADDITIONAL_DRIVE_FOLDERS` - any extra Drive folders to crawl besides
    what's linked in the PDFs (already includes "2 Weeks to £10K").
  - `WRAPPER_FOLDER_NAMES` - add to this list if you spot another
    marketing/membership wrapper folder that should be flattened.
  - `PROGRAMME_RENAMES` - optional, only needed if a source folder's name
    in Drive doesn't match what you want it called in the destination.

## 4. Run it

```
run.bat
```

or, with your virtual environment active:

```
python main.py
```

The first run opens a browser window asking you to sign in to Google and
approve access - after that, `token.json` is reused automatically and you
won't be asked again unless it's revoked or deleted.

While it runs you'll see a single live-updating status line:

```
Folders scanned: 42 | Files discovered: 310 | Uploaded: 128 (4.2 GB) | Duplicates skipped: 6 | Inaccessible/errors: 2 | Programme: Money Mindset | ETA: 12m 30s
```

## Resuming after an interruption

Just run it again. Discovery (crawling) is cheap and always re-runs so it
can pick up anything newly added to the source folders, but nothing is
re-uploaded: every file already imported is recorded in `import_state.db`
and is skipped automatically. If you ever want to start completely from
scratch, delete `import_state.db` (this does not touch anything already
in your destination Drive folder, so you'd also want to clear that out
manually first to avoid duplicates).

## Output

- **`import_log.csv`** - one row per file with columns `timestamp, event,
  name, source_id, programme, dest_path, size_bytes, reason`. `event` is
  one of `imported`, `duplicate`, `inaccessible`, or `skipped` (used for
  broken/unrecognised links and other errors). Check `broken_links` inside
  `import_state.db` for the full list of links that couldn't be resolved,
  including which PDF/page each one came from.
- **`debug.log`** - full verbose log, useful for troubleshooting.
- Your Google Drive destination folder, organised by programme.

## How content gets organised

- Every link is resolved independently. A link to a single file goes
  straight into the destination folder under its own name.
- A link to a folder whose name is a marketing wrapper (see
  `WRAPPER_FOLDER_NAMES`) is treated as transparent: each of its own
  contents is processed as if it had been linked to directly. This also
  applies to wrappers nested inside other wrappers.
- Any other linked folder is treated as one programme. Every file inside
  it (at any depth, with wrapper sub-folders flattened the same way) is
  collected first:
  - If that comes to exactly **one** file, no folder is created - the
    file goes straight into the destination root, exactly like the spec
    asked for single-resource programmes.
  - If there's more than one file, a single destination folder is
    created using the programme's Drive folder name (or its entry in
    `PROGRAMME_RENAMES`), and the internal folder structure is preserved
    underneath it, minus any wrapper folders.
- The only PDFs excluded from upload are ones matching a filename already
  present in your local `PDFs/` folder - i.e. the index PDFs themselves,
  even if a copy of one turns up while crawling Drive.

## Duplicate detection

Applied in this order, exactly as specified:

1. **Drive file ID** - has this exact source file already been imported
   in a previous run?
2. **Content hash** - Google Drive reports an MD5 (and, for many files, a
   SHA-256) checksum as file metadata, so this check never requires
   downloading a file solely to hash it. If a source file has no checksum
   at all (true for native Google Docs/Sheets/Slides, which have no fixed
   binary content), a SHA-256 is computed locally right after it's
   downloaded for upload and checked against previous imports before the
   upload proceeds.
3. **Filename + size** - last-resort fallback.

A defensive extra check also asks the live destination folder directly
before every upload, in case `import_state.db` was ever deleted or lost.

## Why download-and-reupload instead of Drive's "copy" feature

The spec explicitly rules out Google Drive's "Make a Copy" action (which
produces `Copy of ...` files with no control over destination
organisation) and explicitly allows temporary local files as long as
they're deleted immediately. The importer therefore always downloads a
file to a temp path, uploads it into the correctly organised destination
folder under its original name, and deletes the temp file straight away
(even on failure) - nothing is left behind on disk.

Native Google Docs/Sheets/Slides/Drawings have no raw binary content to
download as-is, so these are exported to an equivalent static format
(`.docx`/`.xlsx`/`.pptx`/`.png`), downloaded, and then re-uploaded with
their original Google Workspace mime type - Drive automatically converts
that back into a live, editable Doc/Sheet/Slide in the destination, so
you still end up with a real Google file rather than a flattened export.

## Project structure

```
BeliefCodingImporter/
    main.py                Orchestrates the whole run
    config.py               All settings live here
    pdf_parser.py            Extracts Drive links from the index PDFs
    drive_crawler.py         Recursive crawl + wrapper flattening + programme rules
    drive_uploader.py        OAuth, folder creation, download/upload, retries
    duplicate_detector.py    The three-tier duplicate check
    database.py              SQLite-backed resumable state
    logger.py                CSV logging + live progress display
    requirements.txt
    run.bat
    PDFs/                    Put your index PDFs here (never uploaded)
```

## Troubleshooting

- **"credentials.json not found"** - see step 1 above.
- **A link is reported inaccessible** - the signed-in Google account
  doesn't have access to that file/folder. Check `import_state.db`'s
  `broken_links` table (or grep `import_log.csv` for `inaccessible`) to
  see exactly which link and which source PDF it came from, then confirm
  access from the same Google account you authenticated with.
- **Uploads are slow** - large videos take time to download then
  re-upload; this is expected. `CHUNK_SIZE` and `MAX_RETRIES` in
  `config.py` can be tuned if needed, but the defaults are safe for most
  connections.
- **Rate limited (HTTP 403/429)** - the importer already retries these
  automatically with exponential backoff; if it persists across an entire
  run, wait a while before trying again - Drive's per-user API quota
  resets automatically.
