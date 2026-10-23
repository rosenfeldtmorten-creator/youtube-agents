# Adding a channel

All channels run from this one repository. Each has a folder in `channels/`, and they share the code, the
workflows, the voice and the Google Cloud app. Adding a channel takes about 15 minutes, most of it on YouTube.

## Why the YouTube account step is done by hand

Google doesn't let software create YouTube channels or Google accounts: it asks for a person (phone checks,
captchas), and making accounts automatically breaks YouTube's terms and gets channels removed. You don't
need new Google accounts anyway. One Google account can own many channels as **Brand Accounts**, and the
pipeline logs in to each one separately.

Everything else (the folder, settings, writing guide, uploads, playlists, Shorts) is done by the agents.

## 1. Make the folder (agent)

Either ask Claude in the project chat ("add a channel about X"), or run **Actions > New channel > Run
workflow** with a slug (`space-facts`), a name and one sentence about the channel. On your own computer:

```bash
python -m yta new-channel --slug space-facts --name "Space Facts" --about "One question about space each week."
```

It copies the settings of an existing channel of the same kind (`episode`: narrated charts like Economics in
Charts, `story`: narrated slides like Slow English Stories) and gives the channel its own login secret,
`YT_REFRESH_TOKEN_<SLUG>` (for `space-facts`: `YT_REFRESH_TOKEN_SPACE_FACTS`).

## 2. Make the channel on YouTube (you, once)

1. Sign in to YouTube with the Google account that owns the other channels.
2. Profile picture > **Settings** > **Add or manage your channel(s)** > **Create a channel**. Give it the same
   name as in step 1. This makes a Brand Account channel.
3. Verify the channel's phone number at <https://www.youtube.com/verify> (needed for custom thumbnails).
   One number can verify a couple of channels a year, so use another number if YouTube refuses.
4. Add a picture and banner in YouTube Studio > Customisation, if you have them.

## 3. Get the channel's login token (you, once)

The Google Cloud app from [SETUP.md](SETUP.md) step 2 is shared, so skip that. Then:

1. Open <https://developers.google.com/oauthplayground>, click the gear, tick **Use your own OAuth
   credentials** and paste the Client ID and Client secret.
2. In "Input your own scopes" paste:
   `https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl`
3. Click **Authorize APIs**, choose your Google account and then **the new channel** when asked which one.
4. Click **Exchange authorization code for tokens** and copy the **Refresh token**.
5. In GitHub: **Settings > Secrets and variables > Actions > New repository secret**. Name it exactly as
   step 1 printed (`YT_REFRESH_TOKEN_SPACE_FACTS`) and paste the token.

No workflow needs editing: each run looks up the secret named in the channel's `channel.yaml` and passes only
that one to the upload step.

## 4. Check the login (agent or you)

Run **Actions > Channel login** with the channel's slug. The run shows the name of the YouTube channel the
token uploads to. If it names the wrong channel, redo step 3 and pick the right one.

## 5. Write and switch on

1. Rewrite `channels/<slug>/WRITING_GUIDE.md` for the channel's subject (Claude can do this), and set up a
   scheduled writing task for it like the existing channels have.
2. Make a test video: **Actions > Publish**, channel = the slug, upload unticked.
3. Add the slug to the `ACTIVE_CHANNELS` variable (for example `["money-charts","space-facts"]`). From the
   next day, Publish, Daily Short and Prepare voices run it along with the others.

## Limits to know about

- **Daily upload quota.** One Google Cloud app gets 10,000 API units a day, shared by every channel. One upload
  costs about 1,600 units, so a long video with captions, thumbnail, playlist and comment is about 2,200, and
  a Short about 1,700. That is enough for two or three channels posting a Short a day plus a couple of videos a
  week. Beyond that, either ask for more quota in the
  [audit form](https://support.google.com/youtube/contact/yt_api_form), or make a second Google Cloud app,
  store its keys as new secrets and name them in the channel's `channel.yaml`:

  ```yaml
  youtube:
    client_id_secret: YT_CLIENT_ID_2
    client_secret_secret: YT_CLIENT_SECRET_2
  ```

  A new app starts with private-only uploads until its own audit is approved.
- **Runner time.** Narrating one episode takes about 3 hours on a GitHub runner. Prepare voices runs each
  channel on its own runner, so channels don't wait for each other.
- **Repetitive content.** YouTube doesn't monetise channels that look mass-produced. Give each channel its
  own subject, look and writing guide rather than copies of one another.
