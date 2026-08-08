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
4. By default (`python main.py`, no arguments) it **stops right there**
   and writes `import_plan.txt` - the exact destination structure it
   proposes, for you to review. Nothing is uploaded or created in Drive.
5. Only once you run `python main.py --execute` does it actually create
   folders and upload files - grouping multi-file programmes into their
   own folder and placing single-resource items directly at the
   destination root.
6. Skips anything it has already imported (by Drive file ID, then content
   hash, then filename+size), so re-running the tool after an
   interruption picks up exactly where it left off.
7. Logs everything to `import_log.csv` and prints live progress while it
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

## Updating to a newer version

Whenever there's an update, double-click **`update.bat`**. It downloads
the latest project files from GitHub and replaces them in place -
`credentials.json`, `token.json`, your `PDFs/` folder, and your import
history (`import_state.db` / `import_log.csv` / `import_plan.txt`) are
never touched, so there's no need to re-authenticate, re-add your PDFs,
or lose progress. This replaces the old "download a zip and manually
copy your files over" process entirely.

If this is your first time getting an update this way and `update.bat`
doesn't exist yet in your project folder, open Command Prompt in the
project folder and paste this once:

```
powershell -NoProfile -Command "iwr https://raw.githubusercontent.com/toelang/BeliefCodingImporter/claude/belief-coding-importer-abvyhd/update.ps1 -OutFile update.ps1; .\update.ps1"
```

That fetches the updater itself and runs it immediately - `update.bat`
will be there for you to double-click next time.

## 3. Add your input

- Put every index PDF you have into the `PDFs/` folder.
- Open `config.py` and check:
  - `DESTINATION_MODE` - `"drive"` to upload into a Google Drive folder,
    or `"local"` to save into a folder on this PC instead (see below).
  - `DESTINATION_FOLDER_URL` - used when `DESTINATION_MODE = "drive"`.
  - `LOCAL_DESTINATION_FOLDER` - used when `DESTINATION_MODE = "local"`.
  - `ADDITIONAL_DRIVE_FOLDERS` - any extra Drive folders to crawl besides
    what's linked in the PDFs (already includes "2 Weeks to £10K").
  - `WRAPPER_FOLDER_NAMES` - add to this list if you spot another
    marketing/membership wrapper folder that should be flattened.
  - `PROGRAMME_RENAMES` - optional, only needed if a source folder's name
    in Drive doesn't match what you want it called in the destination.

### Saving to a local folder (e.g. OneDrive) instead of Google Drive

Google Drive has a storage quota, and importing a large library can fill
it up. Setting `DESTINATION_MODE = "local"` sidesteps that entirely: the
importer still reads everything from Google Drive (that's where the
source content lives), crawls and organises it exactly the same way, but
the very last step - the "upload" - becomes "save into a folder on this
PC" instead. Point `LOCAL_DESTINATION_FOLDER` at a path inside your
OneDrive (or Dropbox, etc.) folder, and that app's own desktop client
uploads everything placed there to the cloud automatically - no second
cloud API, no separate Microsoft sign-in, nothing extra to set up.

A few things behave slightly differently in local mode:

- Files already sitting in `LOCAL_DESTINATION_FOLDER` (matching name and
  size) are treated as already imported and left untouched - useful if
  the folder already has some content in it.
- Native Google Docs/Sheets/Slides are saved as their exported static
  file (`.docx`/`.xlsx`/`.pptx`/`.png`) with that extension appended,
  since there's no "live Google file" concept on a local disk.
- Windows has a ~260 character path length limit by default. A handful
  of deeply-nested files with long names could hit this; if a file fails
  with a "path too long" error, either enable long path support (Windows
  Settings, search for "Enable Win32 long paths") or use a shorter
  `LOCAL_DESTINATION_FOLDER`.
- Make sure you have enough free space both on your actual hard drive
  *and* in your cloud storage plan - OneDrive normally keeps a full local
  copy of everything it syncs.

**Switching modes after already importing some files:** the two
destinations don't share history - "already uploaded to Drive" doesn't
carry over to a fresh local import. If you're moving your whole import to
a new destination, delete `import_state.db` first so nothing is skipped
as "already done" when it's only done in the *other* place. (This never
touches the destination itself - it only resets the importer's own memory
of what it's done.)

## 4. Review the plan first (default, safe)

Running the importer with no arguments **never uploads or creates
anything in Google Drive**. It authenticates, crawls every PDF link and
every configured folder read-only, then prints the exact destination
structure it proposes and saves it to `import_plan.txt`:

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

`import_plan.txt` has four parts:

1. A **summary** - counts and total size, broken down into how many files
   will actually upload vs. how many are already imported, duplicates, or
   inaccessible.
2. A **folder tree**, for a quick visual sanity check:
   ```
   (destination root)/
       Working with Your Spirit Animal.mp4  (240.1 MB)
       Reiki 1/
           Reiki Intro.mp4  (190.7 MB)
           Workbook.pdf  (1.9 MB)
       Money Mindset/
           Module 1 - Money Mindset.mp4  (150.2 MB)
           ...
   ```
3. A **full file list** - every single file with its complete destination
   path spelled out, e.g. `Reiki 1/Extras/Bonus Session.mp4`, exactly as
   it will appear once uploaded (or already appears, if marked `[already
   imported]`), so there's no ambiguity about where anything lands.
4. Any **broken or inaccessible links**, with the source PDF and reason.

Check this over carefully - it's the exact structure that will be
created, and nothing in Google Drive has been touched yet.

## 5. Approve and run the real import

Once you're happy with `import_plan.txt`, run it again with `--execute`
to actually create the folders and upload the files:

```
run.bat --execute
```

or:

```
python main.py --execute
```

This uses the same crawl logic as the plan, so the structure it creates
will match what you approved (plus anything newly added to the source
folders since you last checked - re-run the plan first if you want to be
sure). While it runs you'll see a single live-updating status line:

```
Folders scanned: 42 | Files discovered: 310 | Uploaded: 128 (4.2 GB) | Duplicates skipped: 6 | Inaccessible/errors: 2 | Programme: Money Mindset | Remaining: 61.4 GB | ETA: 3h 12m
```

The ETA is based on total remaining **data volume** divided by your
measured upload throughput so far, not a count of files - with imports
this size (often tens of GB, since every file is downloaded then
re-uploaded), a small handful of tiny PDFs uploading first would make a
file-count average wildly optimistic. Expect the ETA to be rough for the
first few files and settle down after that; treat "Remaining" (the raw
GB left) as the more stable number early on.

## Resuming after an interruption

Just run `python main.py --execute` again. Discovery (crawling) is cheap
and always re-runs so it can pick up anything newly added to the source
folders, but nothing is re-uploaded: every file already imported is
recorded in `import_state.db` and is skipped automatically. If you ever
want to start completely from scratch, delete `import_state.db` (this
does not touch anything already in your destination Drive folder, so
you'd also want to clear that out manually first to avoid duplicates).

## Output

- **`import_plan.txt`** - the proposed (or, after `--execute`, actual)
  destination structure, regenerated every run. Files already imported in
  a previous run are marked `[already imported]` when you re-run the plan.
- **`import_log.csv`** - one row per file with columns `timestamp, event,
  name, source_id, programme, dest_path, size_bytes, reason`. `event` is
  one of `imported`, `duplicate`, `inaccessible`, or `skipped` (used for
  broken/unrecognised links and other errors). Only written during
  `--execute` runs. Check `broken_links` inside `import_state.db` for the
  full list of links that couldn't be resolved, including which PDF/page
  each one came from (also listed at the bottom of `import_plan.txt`).
- **`debug.log`** - full verbose log, useful for troubleshooting.
- Your Google Drive destination folder, organised by programme
  (`--execute` only).

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

### When a PDF links straight to individual files, not a folder

Several of the source PDFs (Reiki 1, Reiki 2, the 46-Day Launch
Programme, and several sections inside the two bundle PDFs) link directly
to dozens of individual files with **no Drive folder holding them
together at all** - the relationship only exists in how the PDF lays
them out, which Drive has no record of. Since folder-based grouping
has nothing to go on there, two config-driven mechanisms fill the gap
(see the comments above them in `config.py` for the full reasoning):

- **`PDF_PROGRAMME_DEFAULTS`** - for a PDF that's entirely about one
  programme (matched loosely against the PDF's filename), every link in
  it defaults to that programme. This is what correctly groups Reiki 1,
  Reiki 2, and the 46-Day Launch Programme even though each is just a
  flat list of unrelated individual file links.
- **`FILE_PROGRAMME_OVERRIDES`** - for the two bundle PDFs (Pay Monthly
  Bonuses, Pay in Full Bonuses), a per-PDF default isn't safe: some
  sections there are one cohesive programme (Money Mindset, Confidence
  Masterclass, Business Coaching, Business & Marketing Blueprint,
  Manifestation Coding), while others are just a category heading
  loosely grouping many unrelated one-off bonuses that are correctly
  meant to stay separate (e.g. everything under "Spiritual Development"
  in Pay in Full Bonuses - these already work correctly via their own
  individual Drive folders and should **not** be merged together). That
  distinction isn't reliably detectable from PDF layout alone, so it's
  made explicit, keyed by the exact original filename, built directly
  from an actual discovered file list.

Both only apply to a link that would otherwise land unfoldered at the
destination root - a real Drive folder, when one exists, always wins.

**One flagged uncertainty:** `Business Strategy.mp4` wasn't confidently
mapped to a specific programme (it could plausibly belong to either "6
Steps to 6 Figures" or "Business Coaching Programme" based on the PDF
text, and the filename alone doesn't disambiguate it). It's deliberately
left ungrouped at the destination root rather than guessed at - add a
`FILE_PROGRAMME_OVERRIDES` entry for it once you've checked the video
itself, if you'd like it filed under a programme folder.

If a future plan shows something that should be grouped but isn't (or
vice versa), add or adjust an entry in `config.py` and re-run the plan -
no code changes needed.

### Reorganising files an earlier run already uploaded

Because `add_discovered()` refreshes a file's computed programme/path on
every re-crawl, fixing the grouping logic above (or editing the override
tables) takes effect immediately for files not yet uploaded - and for
files an *earlier* run already placed in the destination, `--execute`
detects the mismatch and performs a Drive-side **move** (metadata only,
no download/re-upload, no duplicate) rather than leaving them stranded in
the old location. Plan mode shows exactly which files this applies to
under "ALREADY-IMPORTED FILES THAT WILL BE MOVED" before you approve
anything.

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

**In plan mode, all of this is simulated so the plan is accurate before
anything runs.** The real check above only knows about files already
marked "uploaded" from a past `--execute` run, so on a first-ever run it
would report zero duplicates even if, say, the same recording was linked
twice under two different names. The plan additionally tracks checksums
and filename+size pairs across the not-yet-uploaded files as it walks
through them, so a duplicate *within the same import* is caught and shown
before you approve anything - not discovered partway through the real
upload.

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

## Engineering decisions & defaults

A few implementation choices weren't specified exactly and were resolved
with a sensible default rather than turned into a question. Documented
here so they're easy to revisit:

- **Programme folder naming.** The destination folder for a multi-file
  programme uses that programme's actual Drive folder name as-is. There's
  no large hand-maintained mapping table from every PDF link title to a
  canonical programme name - if a specific source folder's name doesn't
  match what you want it called, add one line to `PROGRAMME_RENAMES` in
  `config.py` rather than renaming things in Drive.
- **Wrapper folder matching** is a case-insensitive substring match
  against `WRAPPER_FOLDER_NAMES`, applied at any depth (including if a
  link points directly at a wrapper). Add more phrases to that list if
  another marketing wrapper turns up that isn't already covered.
- **Folder-listing loop protection.** Each folder is only listed once per
  run (tracked in memory via the database), both to guard against
  shortcut cycles and to avoid redundant work if the same folder is
  reachable from two different links. Re-running always re-lists from
  scratch so newly added source content is picked up.
- **Duplicate simulation in plan mode** predicts what `--execute` would
  do without being able to see the future (e.g. a permission revoked
  between planning and executing would only surface at execute time as
  "inaccessible"). Treat the plan as accurate for what's true right now.
- **Retries**: transient Drive errors (rate limiting, 5xx, network
  blips) retry up to `MAX_RETRIES` times with exponential backoff before
  a file is marked `error`; permission-denied and not-found responses are
  treated as immediately inaccessible rather than retried, since retrying
  won't fix them.
- **Filenames are never sanitised or altered** for the destination - only
  the local temp filename (used purely as a scratch path on disk) is
  stripped of unusual characters.

## Project structure

```
BeliefCodingImporter/
    main.py                Orchestrates the whole run (plan mode by default, --execute to import)
    config.py               All settings live here
    pdf_parser.py            Extracts Drive links from the index PDFs
    drive_crawler.py         Recursive crawl + wrapper flattening + programme rules
    drive_uploader.py        OAuth, Drive folder creation, download/upload, retries
    local_uploader.py         Local-folder destination backend (DESTINATION_MODE = "local")
    duplicate_detector.py    The three-tier duplicate check
    database.py              SQLite-backed resumable state
    plan_report.py           Builds the proposed structure preview (import_plan.txt)
    logger.py                CSV logging + live progress display
    requirements.txt
    run.bat
    update.bat               Double-click to pull the latest version (see "Updating")
    update.ps1
    PDFs/                    Put your index PDFs here (never uploaded)
```

## Troubleshooting

- **"NO PDFs FOUND" / the plan is missing almost everything** - the `PDFs/`
  folder is empty. PDFs are deliberately excluded from git (they're your
  personal files, not project code), so if you cloned/downloaded this
  project fresh, you must manually copy your index PDFs into `PDFs/`
  yourself before running. The console makes this hard to miss with a
  banner warning, and `import_plan.txt` will only reflect
  `config.ADDITIONAL_DRIVE_FOLDERS` until you do.
- **A filename looks like "Copy of Part 1.mp4"** - this is not something
  the importer does. Filenames are always preserved exactly as they are
  on the source file in Drive; if a source file already has "Copy of" in
  its name (e.g. from someone using Drive's "Make a Copy" before it was
  linked), that name is carried through as-is.
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
