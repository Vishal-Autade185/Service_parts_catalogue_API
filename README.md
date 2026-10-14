# Service Parts Catalogue API

A small web service for the AM-700 bottling machine. It reads three CSV files from the `data/`
folder (`bom.csv`, `parts_master.csv`, `service_parts.csv`) and answers, for any part:
what it is, where it sits in the machine, whether it can be replaced on site, and which machine
serial numbers it fits.

## Step 1: Download the project

1. Open https://github.com/Vishal-Autade185/Service_parts_catalogue_API
2. Click the green **Code** button, then **Download ZIP**.
3. Go to your **Downloads** folder, right-click the ZIP file and choose **Extract All** (Windows)
   or double-click it (macOS / Linux). You now have a folder named
   `Service_parts_catalogue_API-main`.

(Using git instead: `git clone https://github.com/Vishal-Autade185/Service_parts_catalogue_API.git`)

## Step 2: Open a terminal inside that folder

All commands below are typed into a terminal that is opened **inside the project folder**
(the one that contains `README.md`).

- **Windows:** open the folder in File Explorer, **right-click an empty space** inside it and choose
  **Open in Terminal** (Windows 11). On Windows 10: hold **Shift**, right-click an empty space and
  choose **Open PowerShell window here**. Or click the address bar at the top of the window,
  type `powershell` and press **Enter**.
- **macOS:** open the **Terminal** app, type `cd ` (with a space), drag the project folder into the
  Terminal window and press **Enter**.
- **Linux:** right-click an empty space inside the folder and choose **Open in Terminal**.

To check you are in the right place, type `dir` (Windows) or `ls` (macOS / Linux) and press
**Enter**: you should see `README.md`, `data` and `app` in the list.

## Step 3: Run it

Type the command and press **Enter**. Pick **one** option. When the terminal shows `Application startup complete`, open
**http://localhost:8000** in your browser. Press `Ctrl+C` to stop.

### Option 1: Docker (recommended: Windows, macOS and Linux)

1. Install **Docker Desktop** from https://www.docker.com/products/docker-desktop/ and open it
   (wait until it says the engine is running).
2. In the terminal from Step 2, run:

```
docker compose up --build
```

The first start takes 1-2 minutes (downloads); after that, a few seconds.

### Option 2: one script (Linux, needs Python 3.9+)

```
bash run.sh
```

It creates a virtual environment, installs everything and starts the server.

### Option 3: manual (any OS, needs Python 3.9+)

Don't have Python? Install it from https://www.python.org/downloads/ (on Windows, tick
**Add python.exe to PATH** in the installer). Then run these three commands, one at a time:

Windows (PowerShell):

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

macOS / Linux:

```
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --port 8000
```

## Use your own data

Replace the three CSV files in `data/` (same file names), then restart:

- Docker: `docker compose restart`
- Options 2 and 3: stop with `Ctrl+C` and run the start command again.

No code changes are needed. To read CSVs from another folder, set `DATA_DIR` to that folder
before starting; `ROOT_PN` sets the top-level part (default `AS-40000`).

## Run the tests

Run the command that matches how you started the app, in the terminal from Step 2.

**If you used Docker (Option 1)** (Docker Desktop must be running):

```
docker compose run --rm -v ./tests:/srv/tests api python -m pytest -q
```

**If you used Option 2 or 3:** the tests need the `.venv` folder those options create.
Running only Docker does **not** create it. If `.venv` is missing, create it first (one time):

```
python -m venv .venv                                   # Windows
.venv\Scripts\python -m pip install -r requirements.txt

python3 -m venv .venv                                  # macOS / Linux
.venv/bin/python -m pip install -r requirements.txt
```

Then run all tests:

```
.venv\Scripts\python -m pytest -q        # Windows
.venv/bin/python -m pytest -q            # macOS / Linux
```

Expected: `403 passed, 1 skipped` (the skipped test is an optional 1-million-path stress test;
run it with `RUN_SLOW=1`).

## Documentation

- [docs/DATA.md](docs/DATA.md): what I found in the data, the rule for each problem, and how I tested it
- [docs/NOTES.md](docs/NOTES.md): decisions, what I cut, limitations and next steps
- [docs/AI.md](docs/AI.md): AI tools used and what for
- [docs/PRODUCT.md](docs/PRODUCT.md): the full specification the project was built from

## What it serves

| URL | Answer |
|---|---|
| `/` | Test page with a form for each question |
| `/docs` | Interactive API documentation |
| `/health` | `{"status": "ok"}` once ready |
| `/api/validation` | Part counts by status |
| `/api/parts/{part_number}` | Part details: description, revision, status, total quantity, parents, children |
| `/api/parts/{part_number}/paths` | Every path from the top-level part down to this part |
| `/api/serial/{serial}` | How many ready parts fit that machine serial number |

Example: http://localhost:8000/api/parts/FA-30019
