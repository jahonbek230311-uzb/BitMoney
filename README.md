# Bit Money CP Judge

Competitive-programming platform: admin and student panels, Monaco editor, Docker-sandboxed judge
(Python 3, C++17, C17, Java 17, JavaScript/Node.js, Go, Rust, Ruby, and PHP), manual input/output test management, contests with live standings. The interface uses Bit Money branding, an animated responsive landing page, a dedicated theme-selection page (Dark / Light / System), and a redesigned admin dashboard.

**Not built yet:** problem import/export, a system-settings page, Alembic migrations, HTTPS reverse proxy,
backups. Contest standings are computed on the fly from submissions (the `contest_rankings` table is unused).

## Run on Windows
1. Install Docker Desktop (WSL2) and Python 3.12; start Docker Desktop.
2. Double-click `start.bat` (first run: builds the sandbox image, asks for the admin account, creates sample problem).
3. Open `http://localhost:8000`. The window also prints `http://<LAN-IP>:8000` for other devices.

## Cannot log in as admin?
Run `.venv\Scripts\python -m app.cli reset-admin` (new or existing username, new password of 12+ characters). It creates the admin or
fixes the existing account: admin role, active, unlock. `start.bat` now checks for an admin account itself and asks again
until one exists. The login accepts the username in any letter case, or the email.

## Offline classroom / phone hotspot mode
The web app, database, and code judging run locally on the host PC. After first-time setup, students can use it without internet as long as the host PC and all student devices are connected to the same Wi-Fi or phone hotspot.

1. While internet is available, install Python 3.12, Docker Desktop,.
2. Start Docker Desktop and run `start.bat` once to install Python dependencies, build the sandbox image, and create the admin account. These local components remain on the PC for later offline sessions.
3. Turn on the phone hotspot and connect the host PC and student devices to that same hotspot.
4. Run `start.bat` on the host PC. Give students the `http://<LAN-IP>:8000` address printed in the terminal. Do not close the terminal while the class is using the site.
5. If Windows Firewall blocks access, run `open_firewall.bat` as administrator once while the Wi-Fi network is set to Private.

The code editor uses a built-in plain-text editor so it does not need Monaco or another CDN from the internet. Test cases are entered manually by the administrator; automatic test generation is disabled. No internet is needed by student devices. If the phone hotspot isolates connected devices, use a normal Wi-Fi router/access point instead.

## Using it from other devices on the same Wi-Fi
* The server listens on all interfaces. Give students the `http://<LAN-IP>:8000` address printed by `start.bat`.
* Run `open_firewall.bat` once as administrator and set the Wi-Fi network to **Private**.
* If devices still cannot connect, the router may have "client/AP isolation" turned on (guest Wi-Fi does this).
* Traffic is plain HTTP, so use it on a network you trust (classroom/lab), not the open internet.

## Accounts
Public registration is **closed**. Admin > Users creates one account or many at once (team001, team002, ...)
with random passwords, shown once, downloadable as CSV or printable. Set `ALLOW_REGISTRATION=1` to open signup.

## Contests (admin only)
Admin > Contests > New. Set start (your local time) and duration; type public/private(password)/practice;
ICPC or points scoring, wrong-attempt penalty, optional partial points. Add problems (each needs >= 20 manually entered and validated tests),
register participants (or all students), then Start / Pause / Resume / Finish, Hide or Freeze the scoreboard,
Export CSV. All deadlines are checked on the **server clock**; the browser countdown is display only.
* Problems of an unfinished contest are hidden from the normal problem list.
* Pause stops the clock: submissions are rejected and the end time is extended by the pause length on Resume.
* Hidden scoreboard auto-reveals when the contest finishes; Freeze stays until you Unfreeze.
* Admin > Submissions > **Ignore** cancels a submission: it stays in history but never counts in standings or stats.

## Ratings, overall standings, profiles (new)
* **Problem rating:** when adding/editing a problem the admin picks a rating (800, 900, 1000, 1200 ... 3500). The old
  easy/medium/hard label is derived from it (<=1100 easy, <=1700 medium, above hard). Students can filter the problem list
  by rating range and sort by rating. Existing databases are upgraded automatically on start (old problems get 800/1200/1800).
* **Overall standings** (`/standings`, linked in the menu): every student's points = sum of the ratings of the problems they
  solved; *Percent* = those points / the sum of all ratings available now (problems of a running contest do not count until
  it ends; ignored submissions never count). The page refreshes itself every 10 s.
* **Profile:** picture (PNG/JPEG/WebP/GIF, max 1 MB), description (500 chars), email, password. A student's change is only a
  *request*: Admin > Profile requests > Accept/Reject. A password change also needs the current password; after it is accepted
  the user must log in again. Admins' own profile changes apply immediately. Other users can open `/users/<name>` (no email shown).
  Pictures are stored in `uploads/avatars` (set `UPLOAD_DIR` to move it).
* **Automatic problem check:** before a problem is published or added to a contest the server checks that it has a saved
  reference solution, at least one valid sample and 20+ valid tests. The contest page lists every problem and shows why a
  problem is not ready; "Create a new problem for this contest" opens the problem form and brings you back with an
  "Add to contest" button.
* **Contest admin:** searchable user list with "Select shown", or paste usernames; blank problem points default to the problem's rating.
  Standings update by themselves; compile/judge errors (CE/SE) are skipped and never add penalty.

## Tests
* No Docker needed: `python -m unittest tests.test_scoring tests.test_checker tests.test_engine tests.test_security_config`
  (the engine tests use a Linux-only local runner; set `JUDGE_RUNNER=docker` to test the real sandbox).
* Web layer: `pip install -r requirements.txt` then `python -m unittest tests.test_web` and `python -m unittest tests.test_profile_web`
  (run them as separate commands: each sets up its own temporary database). Ranking logic: `python -m unittest tests.test_ranking`.

## Security model
Student code never runs in the web process: each run is a `docker run` with `--network none`, read-only root,
memory/CPU/pids limits, capabilities dropped (a root supervisor keeps SETUID/SETGID/DAC_OVERRIDE and drops the
program to uid 65534), output cap, temp dirs deleted. Passwords: scrypt. Sessions: random token, SHA-256 stored.
CSRF: Origin check on every state-changing request. Login: per-IP rate limit + 5-failure lockout.
Hidden tests are read only by the judge worker and admin endpoints. Run a single server process.

## Automatic tests (new)
Admin > Problems > New: write the title and the statement, keep "Create the tests automatically" ticked. After you press
Create, the server asks a local AI model (Ollama) for a reference solution, an independent brute-force solution, a seeded
generator and the sample. Everything runs in the Docker sandbox; expected outputs come from the reference, and every test small
enough is cross-checked against the brute force (a disagreement marks the test INVALID and the AI gets one chance to fix it).
Input/output format are filled in from the AI answer when you left them empty. Then press **Publish**. The button
"Create tests automatically" on the edit page repeats the run (unpublish first; existing tests are replaced).
* No API key is needed. Install Ollama, run `ollama pull qwen2.5-coder:14b`, and keep Ollama running. By default CP Judge calls `http://127.0.0.1:11434/v1`; set `LLM_BASE_URL` and `LLM_MODEL` to use a different local OpenAI-compatible server. The problem statement is processed by that local model.
* Not supported automatically: interactive problems and problems where several different answers are accepted.

## Standings
Columns: place, user, one column per problem, **Penalty**, **Tried**, **Solved**; refreshes every second. Penalty is the number of
failed attempts on solved problems (time does not matter). Ranking: more solved first, then fewer failed attempts; equal results share a place.
