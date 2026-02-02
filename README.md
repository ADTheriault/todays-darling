# Today's Darling - Hobonichi Scraper

Automated scraper for Shigesato Itoi's daily essays from [1101.com](https://www.1101.com/), with English translation via Claude API and Atom feed generation.

## Features

- **Daily Scraping**: Automatically fetches Itoi's essay from 1101.com at 12:00 JST
- **AI Translation**: Translates Japanese essays to natural, literary English using Claude Sonnet
- **Atom Feed**: Generates an RSS/Atom feed for feed readers
- **Markdown Archives**: Saves both original Japanese and translated English as markdown files
- **Retry Logic**: Automatic retries at 14:00 and 16:00 JST if initial scrape fails
- **Deduplication**: Content hashing prevents duplicate entries

## Project Structure

```
todays-darling/
├── scraper.py                 # Main scraper implementation
├── requirements.txt           # Python dependencies
├── README.md                  # This file
├── .github/
│   └── workflows/
│       └── daily-scrape.yml   # GitHub Actions automation
├── docs/
│   ├── atom.xml              # Generated Atom feed
│   └── archive.json          # JSON archive of all essays
├── originals/                 # Japanese markdown files
│   └── TD-Original-YYYY-MM-DD.md
├── translated/                # English markdown files
│   └── TD-Translated-YYYY-MM-DD.md
└── logs/                      # Optional log files
    └── scrape.log
```

## Setup Instructions

### 1. Create GitHub Repository

```bash
cd ~/Programming-Projects/todays-darling

# Initialize git repository
git init

# Add all files
git add .

# Create initial commit
git commit -m "Initial commit: Hobonichi Scraper V2"

# Create repository on GitHub (using gh CLI)
gh repo create todays-darling --public --source=. --push

# Or manually: create repo on github.com, then:
# git remote add origin https://github.com/YOUR_USERNAME/todays-darling.git
# git branch -M main
# git push -u origin main
```

### 2. Add Anthropic API Key Secret

The scraper requires an Anthropic API key for translation. Add it as a repository secret:

**Option A: Using GitHub CLI**
```bash
gh secret set ANTHROPIC_API_KEY
# Paste your API key when prompted
```

**Option B: Using GitHub Web Interface**
1. Go to your repository on GitHub
2. Click **Settings** (tab at the top)
3. In the left sidebar, click **Secrets and variables** → **Actions**
4. Click **New repository secret**
5. Name: `ANTHROPIC_API_KEY`
6. Secret: Paste your Anthropic API key
7. Click **Add secret**

### 3. Enable GitHub Pages (Optional)

To serve the Atom feed publicly:

1. Go to **Settings** → **Pages**
2. Under "Source", select **Deploy from a branch**
3. Select `main` branch and `/docs` folder
4. Click **Save**

Your feed will be available at: `https://YOUR_USERNAME.github.io/todays-darling/atom.xml`

### 4. Test the Workflow

Trigger a manual run to verify everything works:

**Option A: Using GitHub CLI**
```bash
gh workflow run daily-scrape.yml
gh run watch
```

**Option B: Using GitHub Web Interface**
1. Go to **Actions** tab
2. Click **Daily Hobonichi Scrape** workflow
3. Click **Run workflow** → **Run workflow**

## Schedule

The scraper runs automatically on this schedule (JST = UTC+9):

| Time (JST) | Time (UTC) | Purpose |
|------------|------------|---------|
| 12:00      | 03:00      | Primary scrape |
| 14:00      | 05:00      | Retry 1 (if primary failed) |
| 16:00      | 07:00      | Retry 2 (if retry 1 failed) |

The workflow checks if today's essay has already been scraped before running, so retries are skipped if the primary run succeeded.

## Local Development

### Prerequisites

- Python 3.11+
- Anthropic API key

### Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium

# Set API key
export ANTHROPIC_API_KEY="your-api-key-here"

# Run scraper
python scraper.py
```

## Output Files

### Atom Feed (`docs/atom.xml`)

Standard Atom feed compatible with RSS readers. Contains:
- Last 30 translated essays
- Essay summaries
- Header image for each entry

### JSON Archive (`docs/archive.json`)

Complete archive of all scraped essays with:
- Original Japanese title, author, body
- Translated English title, author, body
- Content hash for deduplication
- Timestamps

### Markdown Files

**Original** (`originals/TD-Original-YYYY-MM-DD.md`):
```markdown
## Title: {Japanese title}
## Date: YYYY-MM-DD
## Author: {Japanese author}
## Content:

{Japanese essay body}
```

**Translated** (`translated/TD-Translated-YYYY-MM-DD.md`):
```markdown
## Title: {English title}
## Date: YYYY-MM-DD
## Author: {English author}
## Content:

{English translation}
```

## Troubleshooting

### Workflow fails with "ANTHROPIC_API_KEY not set"
Ensure you've added the secret correctly. Go to Settings → Secrets and variables → Actions and verify `ANTHROPIC_API_KEY` exists.

### No essay content found
The website structure may have changed. Check that the selectors in `scraper.py` still match the page structure at 1101.com.

### Duplicate essays
The scraper uses content hashing. If the same essay appears twice, it means the content changed slightly. Check `archive.json` for hash values.

## License

This project is for personal use. Essays are copyright Shigesato Itoi / Hobonichi.
