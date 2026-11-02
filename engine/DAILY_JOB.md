# Daily autopilot job for @clip.erz101

Goal: Instagram posts heavily in the two peak windows only: every 30 min from 10:00 to 12:30 and from 17:00 to 19:30 (Dubai time). That's 12 slots a day and nothing outside them.
- Clipping slots (yours): 10:00, 11:00, 11:30, 12:30, 17:00, 18:00, 18:30, 19:30. That's 8 a day. Keep them filled at least 2 days ahead.
- Horror slots (reserved for horror batches): 10:30, 12:00, 17:30, 19:00. If one is still empty less than 24h ahead, fill it with a clipping Reel.

Accounts:
- Metricool brand blogId `7563071`, timezone `Asia/Dubai`, Instagram `clip.erz101`.
- Public video hosting: repo `maximusbol2011-debug/clip-erz101-reels` (branch main). Media URL format:
  `https://raw.githubusercontent.com/maximusbol2011-debug/clip-erz101-reels/main/<path>`

## Steps

1. Clone the repo (add it to the session with add_repo, push access). Run `bash engine/setup.sh`.
2. Call Metricool `getScheduledPosts` for brandId 7563071 from now to 3 days ahead (timezone Asia/Dubai).
   List every empty clipping slot from now to the end of the day after tomorrow, plus any empty horror slot within the next 24h. If there are none, stop and report "queue full".
3. N = the number of empty slots found (normally 8 to 10).
4. Research before writing (WebSearch):
   - This week's trending Instagram hashtags for clipping, video editing, content creators and podcasts.
   - This week's trending Instagram Reels audio and which video formats each one is used with (Later, NapoleonCat and SocialPilot publish weekly roundups).
5. Write N new specs in `engine/specs/<YYYY-MM-DD>/NN.json`. Follow the format docs at the top of `engine/templates.py`. Rules:
   - The niche is clipping: podcast and stream clipping tips, hooks, captions, retention, the editing workflow, the clipper lifestyle, and growth.
   - Every topic must be new. Read `engine/history.json` and do not repeat a topic or hook.
   - Mix the formats roughly evenly: list, mythfact, versus, stat. Use 2 to 4 items each, so each video lasts 10 to 20 s.
   - The hook must be punchy and under 8 words. Every on-screen word must also be spoken (`say`).
   - Write stats only if you're confident they're accurate, or phrase them as rules of thumb.
   - Slug `ap-NNN-short-name`, continuing the numbering in history.json.
   - Add `"caption"`: one line with an emoji and a question or a save/share CTA.
   - Add `"music"`: the trending audio search term that fits this format and mood, or "" if none fits.
6. Render: `cd engine && OUTDIR=../auto python3 render_specs.py specs/<date>/*.json`. Spot-check 2 videos by extracting a frame strip with ffmpeg and looking at it.
7. Commit the specs, the mp4s in `auto/` and the updated history.json, then push to main. Pull --rebase first, because other threads push horror reels to this repo too.
8. Schedule each video in Metricool with `createScheduledPost`, one per empty slot, in order:
   - `providers: [{"network":"instagram"}]`, `instagramData: {"type":"REEL","showReelOnFeed":true,"isAiGenerated":true}`. The voiceover is AI, and Instagram requires the label.
   - text = caption + blank line + 6 to 10 hashtags (2 to 4 trending ones from step 4 plus niche tags: #clipping #clipper #podcastclips #videoediting #editingtips #contentcreator).
   - Music: add `instagramData.audioConfiguration = {"audioId": "<music search term>", "audioVolume": 15, "videoVolume": 100}`.
     If Metricool answers that the audio catalog isn't available (403), schedule the post without music. Never retry a 403, and note it in the report.
     If the term matches several tracks, retry once with the exact numeric id from the candidates list.
     Never mix copyrighted music into the mp4 itself.
   - On a transient error ("Request cancelled"), call getScheduledPosts to check whether the post was created anyway before retrying, so nothing gets scheduled twice.
9. Update `engine/history.json` (`last_scheduled_dubai` and the new topics), then commit and push.
10. Final report (short): how many Reels were scheduled, the time range, the formats used, the music used or why none was used, and any errors.
