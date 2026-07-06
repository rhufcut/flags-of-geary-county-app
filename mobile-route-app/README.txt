Mobile Route App

What this app does:
- Reads the newest route files from either:
  - C:\Users\rhufc\OneDrive\JCMS\Flags of Geary County\outputs
  - mobile-route-app\data\outputs
- Shows each zone and segment in a mobile-friendly web page
- Supports runner-specific links using ?runner=Name
- Protects the app with a shared password
- Lets users tap "Open in Maps" to launch Google Maps

Files:
- server.py: local web server and JSON API
- static\index.html: mobile web app
- run_mobile_route_app.bat: launcher
- run_public_route_app.bat: starts the local app plus ngrok public tunnel
- config.json: shared password and optional public base URL
- sync_route_data.py: copies the newest route manifest and links CSV into the deployable data folder
- requirements.txt: Python package list for Render/Docker
- render.yaml: Render deployment blueprint
- Dockerfile / DEPLOYMENT.md: internet-deployment prep

How to use:
1. Run the route builder first so fresh output files exist.
2. Double-click run_mobile_route_app.bat
3. Open http://127.0.0.1:8042 on the same computer
4. On phones on the same Wi-Fi, open:
   http://YOUR-COMPUTER-IP:8042

Public internet access:
1. Double-click run_public_route_app.bat
2. Sign in to the mobile app with the shared password from config.json
3. Use the public HTTPS ngrok URL shown in the ngrok window

Notes:
- This is a strong version 1 mobile web app.
- Default shared password is stored in config.json. Change it before wider sharing.
- For always-on public hosting, use the included Render files and DEPLOYMENT.md guidance.
