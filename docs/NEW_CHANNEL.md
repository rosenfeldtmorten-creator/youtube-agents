# Adding a channel

All channels run from this one repository. Each has a folder in `channels/`, and they share the code, the
workflows, the voice and the Google Cloud app. After the one-time setup below, a new channel takes about five
minutes of your time: two on YouTube and one to sign in. The agents do the rest.

| Step | Who | Time |
| --- | --- | --- |
| 1. Make the folder | agent | |
| 2. Make the channel on YouTube | you | 2 min |
| 3. Connect its login | you sign in, agent does the rest | 1 min |
| 4. Write, test and switch on | agent | |

## What can't be automated, and why

Google doesn't let software create YouTube channels or Google accounts: it asks for a person (phone checks,
captchas), and making accounts automatically breaks YouTube's terms and gets channels removed. The same goes for
signing up to Pixabay. And only you can tell Google that the app may upload to your channel. So those stay
with you, cut down to the fewest clicks. You don't need new Google accounts: one Google account can own many
channels as **Brand Accounts**, and the pipeline logs in to each one separately.

## One-time setup

Done once for all channels, in [SETUP.md](SETUP.md): the Google Cloud app (step 2), and under
**Connect channels** the sign-in app for devices, the `ADMIN_TOKEN` secret and the Pixabay key. Connect channel
tells you if any of them is missing.

## 1. Make the folder (agent)

Either ask Claude in the project chat ("add a channel about X"), or run **Actions > New channel > Run
workflow** with a slug (`space-facts`), a name and one sentence about the channel. On your own computer:

```bash
python -m yta new-channel --slug space-facts --name "Space Facts" --about "One question about space each week."
```

It copies the settings of an existing channel of the same kind (`episode`: narrated charts like Economics in
Charts, `story`: narrated slides like Slow English Stories, `clips`: narrated footage Shorts like Nature
Unleashed) and gives the channel its own login secret, `YT_REFRESH_TOKEN_<SLUG>` (for `space-facts`:
`YT_REFRESH_TOKEN_SPACE_FACTS`).

## 2. Make the channel on YouTube (you, once)

1. Sign in to YouTube with the Google account that owns the other channels.
2. Profile picture > **Settings** > **Add or manage your channel(s)** > **Create a channel**. Give it the same
   name as in step 1. This makes a Brand Account channel.
3. Verify the channel's phone number at <https://www.youtube.com/verify> (needed for custom thumbnails).
   One number can verify a couple of channels a year, so use another number if YouTube refuses.
4. Add a picture and banner in YouTube Studio > Customisation, if you have them.

## 3. Connect its login (you sign in, once)

Ask Claude to connect the channel, or run **Actions > Connect channel** with the slug. Either way you get a
short code, in the chat or in the run's first job:

1. Open <https://www.google.com/device> on any phone or computer and type the code.
2. Choose your Google account, then **the new channel** when Google asks which one. Google warns that the app is
   unverified: click **Advanced** and continue. It is your own app.

The run then checks that the login uploads to a channel with the name in `channel.yaml` and saves it as the
`YT_REFRESH_TOKEN_<SLUG>` secret. If it belongs to another channel it is not saved: run it again and pick the
right one (tick **any name** if the YouTube name is deliberately different). Nobody copies or pastes the token.

The device sign-in app is a second app in the same Google Cloud project, so it shares the same upload quota.
The run adds two lines to the channel's `channel.yaml` naming it, because a login only works with the app that
made it.

<details><summary>Without Connect channel (the old way)</summary>

1. Open <https://developers.google.com/oauthplayground>, click the gear, tick **Use your own OAuth
   credentials** and paste the Client ID and Client secret of the main app.
2. In "Input your own scopes" paste:
   `https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl`
3. Click **Authorize APIs**, choose your Google account and then **the new channel** when asked which one.
4. Click **Exchange authorization code for tokens** and copy the **Refresh token**.
5. In GitHub: **Settings > Secrets and variables > Actions > New repository secret**. Name it exactly as
   step 1 printed (`YT_REFRESH_TOKEN_SPACE_FACTS`) and paste the token.
6. Run **Actions > Channel login** with the slug to check which channel it uploads to.

</details>

## 4. Write, test and switch on (agent)

1. Rewrite `channels/<slug>/WRITING_GUIDE.md` for the channel's subject, and set up a scheduled writing task
   for it like the existing channels have.
2. Make a test video: **Actions > Publish**, channel = the slug, upload unticked.
3. Run **Actions > Switch channel** with the slug and **on** (or tick **switch on** in Connect channel). It
   adds the slug to the `ACTIVE_CHANNELS` variable; from the next day, Publish, Daily Short, Prepare voices and
   Compilation run it along with the others. **off** takes it out again.

No workflow needs editing: they pass every secret to the upload step, which picks the one named in the
channel's `channel.yaml`.

## For Claude: connecting a channel from the chat

1. Trigger `connect-channel.yml` on `main` with `channel=<slug>` (and `switch_on=true` only if the owner asked).
2. When its `code` job finishes, read that job's check-run annotations: the notice titled
   "Sign in to connect ..." holds the link and the code. A failure there lists the missing one-time secrets.
3. Post the link and code to the owner and say which channel to pick. The code lasts about 30 minutes.
4. The `save` job's annotations say which channel the login uploads to, or why it wasn't saved.

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
