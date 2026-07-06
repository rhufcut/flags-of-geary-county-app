Render Deployment

This app is now prepared for Render deployment.

What changed:
- `server.py` now supports a hosted route-data folder inside `mobile-route-app\\data\\outputs`
- `requirements.txt` was added for Python package installs
- `render.yaml` was added for Render web-service setup
- `sync_route_data.py` was added to copy the newest route files into the app before deployment

Recommended workflow

1. Build routes on your home computer first.
   Run your desktop route builder so it creates fresh files in:
   `C:\Users\rhufc\OneDrive\JCMS\Flags of Geary County\outputs`

2. Copy the newest route data into the mobile app folder.
   From inside `mobile-route-app`, run:

   `python sync_route_data.py`

   That refreshes these deployable files:
   - `data\outputs\flags_route_manifest.json`
   - `data\outputs\flags_google_maps_links.csv`

3. Put the `mobile-route-app` folder itself in a Git repository and push it to GitHub.
   Render deploys most easily from GitHub, and using this folder as the repo root keeps the setup simple.

4. Create a Render Web Service.
   Point Render at that repository and let it use:
   - `buildCommand`: `pip install -r requirements.txt`
   - `startCommand`: `python server.py`

5. Set environment variables in Render.
   Add these in the Render dashboard:
   - `ROUTE_APP_PASSWORD=your-admin-password`
   - `RUNNER_SECRET=your-runner-secret`
   - `PUBLIC_BASE_URL=https://your-app-name.onrender.com`

6. Deploy.
   After the first successful deploy, your app will be reachable at its public Render URL.

Updating routes later

Each time you build a new route run:
1. Run the desktop route builder locally.
2. Run `python sync_route_data.py`
3. Commit the updated `data\outputs` files.
4. Push to GitHub.
5. Render will redeploy automatically.

Important notes

- Runner/admin status is stored in `data\flag_status.sqlite3`.
- On Render, local disk content can be reset during redeploys unless you add persistent storage.
- For a first hosted version, this is fine for testing.
- For long-term production use, I recommend moving status storage to Postgres.

Docker option

You can also run the app with Docker:
- `docker build -t geary-routes .`
- `docker run -p 8042:8042 -e ROUTE_APP_PASSWORD=your-admin-password -e PUBLIC_BASE_URL=http://localhost:8042 geary-routes`
