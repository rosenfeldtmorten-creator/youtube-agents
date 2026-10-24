# Setup

Everything here is free. You only do it once. Do the steps in this order.

## 1. Make the YouTube channel

1. Sign in to YouTube with the Google account that will own all three channels.
2. Click your profile picture, then **Settings**, then **Add or manage your channel(s)**, then **Create a channel**. This makes a Brand Account channel.
3. Name it (for example "Slow English Stories").
4. Verify the channel's phone number at <https://www.youtube.com/verify>. Custom thumbnails need this.

Repeat for the other two channels later. Each channel gets its own login token in step 3.

## 2. Make a Google Cloud project

1. Open <https://console.cloud.google.com/> and create a project called `youtube-agents`.
2. Go to **APIs & Services > Library**, search for **YouTube Data API v3**, and click **Enable**.
3. Go to **APIs & Services > OAuth consent screen** (also called **Google Auth Platform**):
   - User type: **External**. App name: `youtube-agents`. Use your own email for the contact fields.
   - Under **Audience**, add your own Gmail address as a test user, then click **Publish app** so the status is **In production**. If you leave it in Testing, the login expires after 7 days and uploads stop.
4. Go to **APIs & Services > Credentials > Create credentials > OAuth client ID**:
   - Application type: **Web application**.
   - Under **Authorized redirect URIs**, add `https://developers.google.com/oauthplayground`
   - Click **Create**. Keep the **Client ID** and **Client secret** for step 4.

Videos uploaded through a new API project are locked to **private** until Google approves an audit. Request it early with the
[YouTube API Services audit form](https://support.google.com/youtube/contact/yt_api_form). Say it is a personal tool that uploads videos to your own channels.

## 3. Get a login token for the channel (in your browser)

1. Open <https://developers.google.com/oauthplayground>.
2. Click the gear icon at the top right, tick **Use your own OAuth credentials**, and paste your Client ID and Client secret.
3. In the box on the left ("Input your own scopes"), paste exactly:
   `https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl`
4. Click **Authorize APIs**. Choose your Google account, then **choose the Slow English Stories channel** when asked which account or channel to use. Google warns that the app is unverified: click **Advanced** and continue. It is your own app.
5. Click **Exchange authorization code for tokens**. Copy the **Refresh token**.

## 4. Background photos (optional)

Without a key, videos use generated colour backgrounds. If Pexels is issuing API keys again, you can get a free one at
<https://www.pexels.com/api/> and add it as the `PEXELS_API_KEY` secret below to use stock photos instead.

## 5. Store the secrets in GitHub

In the repository on GitHub, open **Settings > Secrets and variables > Actions > New repository secret** and add:

| Name | Value |
| --- | --- |
| `YT_CLIENT_ID` | Client ID from step 2 |
| `YT_CLIENT_SECRET` | Client secret from step 2 |
| `YT_REFRESH_TOKEN_ENGLISH_STORIES` | Refresh token from step 3, for the English channel |
| `YT_REFRESH_TOKEN_MONEY_CHARTS` | Refresh token from step 3, repeated for the finance channel |
| `PEXELS_API_KEY` | Optional: key from step 4 |

Each further channel only needs its own `YT_REFRESH_TOKEN_<SLUG>` secret: see [NEW_CHANNEL.md](NEW_CHANNEL.md).

Never paste these into a chat, an issue or a file in the repository.

## 5b. Connect channels without copying tokens (optional, recommended)

These three let the agents add channels with only a sign-in from you ([NEW_CHANNEL.md](NEW_CHANNEL.md) step 3).
Each is done once for every channel.

1. **Sign-in app for devices.** In <https://console.cloud.google.com/> (same `youtube-agents` project) open
   **APIs & Services > Credentials > Create credentials > OAuth client ID**, choose application type
   **TVs and Limited Input devices**, name it `youtube-agents device` and click **Create**. Add its Client ID
   and Client secret as the secrets `YT_DEVICE_CLIENT_ID` and `YT_DEVICE_CLIENT_SECRET`.
2. **A GitHub token that may save secrets.** GitHub's own workflow token can't write secrets, so the workflows
   use one of yours. Open <https://github.com/settings/personal-access-tokens/new>, name it `youtube-agents admin`,
   pick an expiry, **Only select repositories** > `youtube-agents`, and under **Repository permissions** set
   **Secrets** and **Variables** to **Read and write**. Generate it and add it as the secret `ADMIN_TOKEN`.
   It can do nothing outside those two settings of this repository. When it expires, Connect channel says so;
   make a new one the same way.
3. **Pixabay key** (for footage channels such as Nature Unleashed). Make a free account at
   <https://pixabay.com/accounts/register/>, then open <https://pixabay.com/api/docs/>: your key is shown under
   **Parameters > key**. Add it as the secret `PIXABAY_API_KEY`. One key serves every channel.

## 6. Add your voice

Record **about one minute** of yourself reading any English text calmly, in a quiet room. A phone is fine.
Upload it in the project chat. Claude cuts the cleanest 10-20 seconds and saves it as `voice/reference.wav`, which the voice clone copies.

## 7. Test, then switch on

1. In GitHub, open **Actions > Publish > Run workflow**, keep **upload** unticked, and run it.
   When it finishes, download the test video from the run's **Artifacts** and watch it.
2. If you like it, run it again with **upload** ticked. That uploads the first video.
3. To let it run by itself every day, go to **Settings > Secrets and variables > Actions > Variables** and add:
   - `AUTOPUBLISH` with the value `true`
   - `ACTIVE_CHANNELS` with the channels that should publish, for example `["english-stories","money-charts"]`

The pacing in `channels/<channel>/channel.yaml` decides how often a video goes out (3 a week for Slow English).
