Alpha Delta Vualt

One-click Windows start:
1. Double-click START_LUCY.bat
2. Alpha Delta Vualt will install dependencies if needed, build if needed, then open locally
3. Use STOP_LUCY.bat to stop the local server
4. START_LUCY_HIDDEN.vbs launches the same app hidden/minimized

Requirements:
- Node.js 18+

Notes:
- This build is local-only.
- No Google or cloud AI services are required.
- If the app does not auto-open, browse to http://127.0.0.1:4173


Repacked build: node_modules removed to avoid Windows zip extraction/path issues.
Run START_LUCY.bat and it will install dependencies if needed, then start the app.
