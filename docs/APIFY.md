# Collecting with Apify (TikTok, YouTube, Facebook, Instagram, X, Reddit, websites)

Apify (apify.com) runs ready-made scrapers called **Actors**. Tarbiyah Hub starts an Actor with your settings,
waits for it to finish, and imports the results (posts, videos, captions, pages) into the library, where they
are classified, indexed and used in research like every other source.

**Cost:** Apify bills your Apify account for each run. The free plan includes a small monthly credit. Tarbiyah
Hub never runs an Actor without your token and limits every day by:

| Setting (Dashboard > Settings) | Default | Meaning |
|---|---|---|
| `apify_daily_run_limit` | 5 | Actor runs per day |
| `apify_max_items_per_run` | 50 | Results per run |
| `apify_max_charge_usd_per_run` | 0.5 | Maximum spend per run (pay-per-event Actors) |
| `apify_run_timeout_seconds` | 900 | Maximum run time |

Also set a monthly usage limit in Apify Console (Billing > Limits) as a second safety net.

**Responsibility:** collect only public content, and respect each platform's terms and people's privacy.
Prefer pages, channels and accounts of institutions and educators over private individuals.

## Step 1: Get your Apify token (once)

1. Create an account at https://apify.com.
2. In Apify Console open **Settings > API & Integrations** and copy your **Personal API token**.
3. Open the `.env` file in the Tarbiyah Hub folder with Notepad and fill in: `APIFY_TOKEN=apify_api_xxxxxxxx`
4. Save, then restart Tarbiyah Hub (`stop.bat`, then `start.bat`).
5. On the dashboard's Settings page, "apify_token" shows as configured.

## Step 2: Choose the Actor in Apify Store

1. Go to https://apify.com/store and search for the platform (e.g. "TikTok scraper").
2. Open the Actor and note its **ID**, shown under its name, like `clockworks/tiktok-scraper`.
3. Open the **Input** tab. Fill in what you want (search words, channels, pages) and switch to the **JSON** view.
   Copy that JSON. This is the most reliable way to get the input right, because Actors change their inputs.
4. Optional: click **Start** once in Apify Console to see what the results look like and what a run costs.

## Step 3: Add it as a source in Tarbiyah Hub

1. Dashboard > **Sources** > **Add source**.
2. Type: **Apify Actor**. Name: e.g. "TikTok – tarbiyah".
3. Settings (JSON): the platform templates are below. Paste your copied Input JSON as the value of `"input"`.
4. Schedule: how often it runs, in minutes (1440 = once a day).
5. Save, then click **Run now**. Watch the source's health and the **Jobs** page; the results appear in the **Library**.

Fields:
- `actor`: the Actor ID from Step 2
- `input`: the Input JSON from Step 2
- `platform`: `tiktok`, `youtube`, `facebook`, `instagram`, `x`, `reddit` or `web` (used as a label)
- `resource_type`: `video`, `social_post` or `article`
- `max_items`: results per run
- `language`: optional, `ar` or `en`
- `use_for_research`: `true` lets the research agent also run this Actor for its questions (each question costs one run)
- `search_input`: the input used for research questions; write `{query}` where the search words go
- `field_map`: only if results import with empty titles or text (see "If results look wrong")

## Templates per platform

The Actor names below were popular choices when this guide was written. Check that the Actor still exists, and
always prefer the Input JSON you copy from its page.

**TikTok**
```json
{
  "actor": "clockworks/tiktok-scraper",
  "platform": "tiktok",
  "resource_type": "video",
  "max_items": 30,
  "input": {"searchQueries": ["تربية الأطفال", "islamic parenting"], "resultsPerPage": 15,
            "shouldDownloadSubtitles": true, "shouldDownloadVideos": false, "shouldDownloadCovers": false}
}
```
For specific accounts, use the Actor's profiles field, e.g. `"profiles": ["account_name"]`.

**YouTube** (for search, playlists and long transcripts; channel monitoring also works free without Apify)
```json
{
  "actor": "streamers/youtube-scraper",
  "platform": "youtube",
  "resource_type": "video",
  "max_items": 20,
  "input": {"searchQueries": ["تربية الأبناء", "islamic parenting"], "maxResults": 10,
            "downloadSubtitles": true, "subtitlesLanguage": "any"}
}
```

**Facebook** (public pages)
```json
{
  "actor": "apify/facebook-posts-scraper",
  "platform": "facebook",
  "resource_type": "social_post",
  "max_items": 30,
  "input": {"startUrls": [{"url": "https://www.facebook.com/PAGE_NAME"}], "resultsLimit": 20}
}
```

**Instagram** (public accounts / hashtags)
```json
{
  "actor": "apify/instagram-scraper",
  "platform": "instagram",
  "resource_type": "social_post",
  "max_items": 30,
  "input": {"directUrls": ["https://www.instagram.com/ACCOUNT_NAME/"], "resultsType": "posts", "resultsLimit": 20}
}
```

**X (Twitter)**
```json
{
  "actor": "apidojo/tweet-scraper",
  "platform": "x",
  "resource_type": "social_post",
  "max_items": 50,
  "input": {"searchTerms": ["تربية الأبناء", "#tarbiyah"], "maxItems": 50}
}
```

**Reddit**
```json
{
  "actor": "trudax/reddit-scraper-lite",
  "platform": "reddit",
  "resource_type": "social_post",
  "max_items": 50,
  "input": {"searches": ["islamic parenting"], "maxItems": 50, "skipComments": true}
}
```

**Any website** (e.g. sites that block simple crawlers)
```json
{
  "actor": "apify/website-content-crawler",
  "platform": "web",
  "resource_type": "article",
  "max_items": 50,
  "input": {"startUrls": [{"url": "https://example.org/articles"}], "maxCrawlPages": 50}
}
```

**Let the research agent use an Actor:** add these two fields to any of the above:
```json
"use_for_research": true,
"search_input": {"searchQueries": ["{query}"], "resultsPerPage": 10, "shouldDownloadSubtitles": true}
```

## If results look wrong

Tarbiyah Hub recognises the common result fields (url, text/caption/description, author, date, subtitles). If an
Actor uses other names, open one result in Apify Console (the run's **Storage > Dataset**, JSON view) and map the
fields yourself. Use dots for nested fields:
```json
"field_map": {"url": "postUrl", "text": "content.body", "author": "owner.username", "date": "publishedTime",
              "transcript": "captions"}
```

## What happens during a run

- The run starts with your caps on items and cost. The run id is saved, so if the computer restarts during a
  run, Tarbiyah Hub continues checking the same run instead of paying for a new one.
- A run that fails on Apify's side is retried later as a new run (up to 4 attempts). Errors are shown on the
  Sources and Jobs pages.
- Results that are already in the library (same URL) are not duplicated.
- When the daily run limit is reached, runs wait until the next day.
