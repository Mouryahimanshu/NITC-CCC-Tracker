# Vercel deployment

Deploy this repository as two Vercel projects so the Vite site and FastAPI API can be configured independently while sharing the same GitHub repository.

## API project

1. Import `1prc/NITC-CCC-Mail-tracker` into Vercel.
2. Set **Root Directory** to `backend` and deploy. Vercel detects the FastAPI application in `app/main.py`.
3. Add these Production environment variables in Project Settings:
   - `DATABASE_URL`: Neon connection string for the `production` branch.
   - `JWT_SECRET_KEY`: a unique random value at least 24 characters long.
   - `FRONTEND_ORIGIN`: the deployed frontend origin, for example `https://your-frontend.vercel.app`.
   - `APP_ENV`: `production`.
   - `ACCESS_TOKEN_MINUTES`: `30`.
4. Redeploy after adding the environment variables. Verify `/health` and `/docs` on the API deployment.

## Frontend project

1. Import the same GitHub repository as a second Vercel project.
2. Set **Root Directory** to `frontend`. Use the Vite framework preset, `npm run build`, and `dist` as the output directory.
3. Add the Production environment variable `VITE_API_BASE_URL` with the API deployment origin followed by `/api/v1`, for example `https://your-api.vercel.app/api/v1`.
4. Deploy and check the schedule, faculty login, and admin login against the production API.

If the frontend's production domain changes, update `FRONTEND_ORIGIN` on the API project and redeploy it. For preview deployments, add the relevant preview origins to the comma-separated `FRONTEND_ORIGIN` value if previews need API access.

## Gmail worker

The mailbox poller is a separate long-running process (`backend/worker.py`) and is not started by the request-driven FastAPI Vercel deployment. Keep it running on a worker host or development machine with `GMAIL_MAILBOX`, `GMAIL_CLIENT_SECRET_FILE`, `GMAIL_TOKEN_FILE`, `GMAIL_ALLOWED_SENDERS`, and `DATABASE_URL` configured. Do not upload OAuth client secrets or token files to Git.

Never commit production environment values. Configure them in Vercel's Environment Variables settings.
