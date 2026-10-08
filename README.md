# Job-Agent — your RevOps skills coach

An AI agent that checks what the Revenue Operations (RevOps) job market is paying for right now, compares it to your skills in HubSpot, Apollo and beyond, and tells you what to learn next.

## How it works

Each run takes two steps:

1. **Research.** Claude searches the web for recent RevOps job postings, salary data, HubSpot and Apollo product updates, and community trends.
2. **Coach.** Claude compares that research with your `profile.yaml`, the practice you've logged, and your last report. It then writes a ranked plan to `reports/YYYY-MM-DD.md`.

Each report includes:
- What the market wants right now, with sources
- 3–5 priority skills, each with a why, an analogy, a two-week hands-on project, and resources
- A checklist for the coming week
- Your progress since the last report
- Honest pushback, such as "your SQL rating looks inflated" or "your target role needs Salesforce"
- A glossary of every acronym used

## Setup (one time)

1. **Fill in `profile.yaml`.** Rate yourself honestly from 1 to 5 and set your target roles. The plan can only be as good as this file.
2. **Get an Anthropic API key** at https://console.anthropic.com.
3. **Run it locally:**
   ```bash
   pip install -r requirements.txt
   export ANTHROPIC_API_KEY=sk-ant-...
   python agent.py report
   ```

## Weekly updates, automatically

`.github/workflows/weekly-report.yml` runs every Monday. It commits the report and **opens a GitHub issue**, so GitHub emails it to you.

To turn it on, go to the repo's **Settings → Secrets and variables → Actions** and add a secret named `ANTHROPIC_API_KEY`. You can also run it by hand from the **Actions** tab ("Run workflow").

## Log your progress

When you practice or ship something, log it so the next report can account for it:

```bash
python agent.py log "Built a lead-scoring model in HubSpot using engagement + firmographic properties"
```

You can also re-rate yourself in `profile.yaml` at any time.

## Cost

Each report makes about two Claude Opus calls plus up to 12 web searches, which usually comes to well under $1. Running it weekly costs a few dollars a month.
