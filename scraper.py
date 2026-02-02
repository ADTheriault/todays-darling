#!/usr/bin/env python3
"""
Hobonichi Scraper V2 - Fresh Implementation

Scrapes Shigesato Itoi's daily essay from 1101.com,
translates it via Claude API, generates Atom feed,
and creates markdown archives.

New in V2:
- Markdown archival system (originals/ and translated/)
- JST timezone-aware scheduling
- Retry logic for failed scrapes
- Enhanced logging
"""

import os
import re
import json
import hashlib
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup
from anthropic import Anthropic, APIError
from feedgen.feed import FeedGenerator


# =============================================================================
# Configuration
# =============================================================================

ESSAY_URL = "https://www.1101.com/"
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "docs"
ORIGINALS_DIR = BASE_DIR / "originals"
TRANSLATED_DIR = BASE_DIR / "translated"
LOGS_DIR = BASE_DIR / "logs"

FEED_FILE = OUTPUT_DIR / "atom.xml"
ARCHIVE_FILE = OUTPUT_DIR / "archive.json"

# Image URLs (self-hosted for reliability)
DARLING_IMAGE_URL = "https://adtheriault.github.io/todays-darling/images/darling.png"
HOBONICHI_ICON_URL = "https://adtheriault.github.io/todays-darling/images/hobonichi-logo.png"

# Original source URL for attribution
SOURCE_URL = "https://www.1101.com/"

# GitHub Pages base URL
PAGES_BASE_URL = "https://adtheriault.github.io/todays-darling/"

# Timezone
JST = ZoneInfo("Asia/Tokyo")
UTC = ZoneInfo("UTC")

# Minimum content length to consider valid
MIN_BODY_LENGTH = 200


# =============================================================================
# Logging Setup
# =============================================================================

def setup_logging() -> logging.Logger:
    """Configure logging for console and optional file output."""
    logger = logging.getLogger("hobonichi-scraper")
    logger.setLevel(logging.INFO)

    # Console handler (for GitHub Actions output)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler (optional, for persistent history)
    try:
        LOGS_DIR.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(LOGS_DIR / "scrape.log", encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(console_format)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Could not set up file logging: {e}")

    return logger


log = setup_logging()


# =============================================================================
# Timezone Utilities
# =============================================================================

def get_jst_now() -> datetime:
    """Get current time in JST."""
    return datetime.now(JST)


def get_jst_date_string() -> str:
    """Get current date in JST as YYYY-MM-DD."""
    return get_jst_now().strftime("%Y-%m-%d")


def format_iso_utc(dt: datetime) -> str:
    """Format datetime as ISO 8601 in UTC."""
    return dt.astimezone(UTC).isoformat()


# =============================================================================
# Scraping Functions (preserved from V1)
# =============================================================================

def scrape_essay() -> Optional[dict]:
    """
    Fetch and extract Itoi's daily essay from 1101.com using Playwright.

    Returns dict with: title, author, body, date, hash
    Returns None if scraping fails or content is insufficient.
    """
    log.info(f"Starting scrape at {get_jst_now().strftime('%Y-%m-%d %H:%M:%S JST')}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(ESSAY_URL, timeout=30000)
            page.wait_for_timeout(2000)  # Wait for JS to render

            html = page.content()
            browser.close()
    except PlaywrightTimeout:
        log.error("Playwright timeout while loading page")
        return None
    except Exception as e:
        log.error(f"Playwright error: {e}")
        return None

    soup = BeautifulSoup(html, 'html.parser')

    title = None
    author = None
    body = None

    # Strategy 1: Use specific selectors (like hellodarling)
    title_el = soup.select_one("div.darling-title h2")
    author_el = soup.select_one("div.darling-title h3")
    body_el = soup.select_one("div.darling-text")

    if title_el and title_el.get_text(strip=True):
        title = title_el.get_text(strip=True)
    else:
        # Fallback: extract title from x-data attribute
        darling_div = soup.select_one("div.darling")
        if darling_div and darling_div.has_attr("x-data"):
            match = re.search(r"darlingTitle:\s*`(.*?)`", darling_div["x-data"])
            if match:
                title = match.group(1)

    if author_el and author_el.get_text(strip=True):
        author = author_el.get_text(strip=True)

    if body_el:
        # Get all paragraphs from the body
        paragraphs = body_el.find_all('p')
        if paragraphs:
            # Process each <p> tag, handling <br> as line breaks within
            all_paragraphs = []
            for p_tag in paragraphs:
                lines = []
                for elem in p_tag.children:
                    if isinstance(elem, str):
                        text = elem.strip()
                        if text:
                            lines.append(text)
                    elif elem.name == 'br':
                        # <br> represents a line break, join current and start new line
                        pass  # Just continue, the next text will be on a new logical line
                    elif hasattr(elem, 'get_text'):
                        text = elem.get_text(strip=True)
                        if text:
                            lines.append(text)

                if lines:
                    # Join lines within this <p> with newlines
                    all_paragraphs.append('\n'.join(lines))

            # Join paragraphs with double newlines
            body = '\n\n'.join(all_paragraphs)
        else:
            # No <p> tags - preserve line breaks from <br> tags
            for br in body_el.find_all('br'):
                br.replace_with('\n')
            body = body_el.get_text()
            lines = [line.strip() for line in body.split('\n') if line.strip()]
            body = '\n'.join(lines)

    # Strategy 2: Fallback to broader search if specific selectors fail
    if not body:
        for section in soup.find_all(['div', 'section', 'article']):
            text = section.get_text()
            if '糸井重里' in text and len(text) > 500:
                paragraphs = section.find_all('p')
                if paragraphs:
                    # Process each <p> tag, handling <br> as line breaks within
                    all_paragraphs = []
                    for p_tag in paragraphs:
                        lines = []
                        for elem in p_tag.children:
                            if isinstance(elem, str):
                                t = elem.strip()
                                if t:
                                    lines.append(t)
                            elif elem.name == 'br':
                                pass
                            elif hasattr(elem, 'get_text'):
                                t = elem.get_text(strip=True)
                                if t:
                                    lines.append(t)
                        if lines:
                            all_paragraphs.append('\n'.join(lines))
                    body = '\n\n'.join(all_paragraphs)
                    h_tag = section.find(['h1', 'h2', 'h3'])
                    if h_tag and not title:
                        title = h_tag.get_text(strip=True)
                    break

    if not body or len(body) < MIN_BODY_LENGTH:
        log.error(f"Could not extract essay content (body length: {len(body) if body else 0})")
        return None

    # Clean up the essay text while preserving paragraph breaks
    paragraphs = body.split('\n\n')
    cleaned_paragraphs = []
    seen_paragraphs = set()
    for para in paragraphs:
        # Clean within paragraph (handle any single newlines)
        para_lines = para.split('\n')
        cleaned_para_lines = []
        for line in para_lines:
            # Skip footer lines about update times
            if 'ほぼ日の更新時間' in line:
                continue
            cleaned_para_lines.append(line)
        para = '\n'.join(cleaned_para_lines).strip()

        if not para:
            continue
        # Skip duplicate paragraphs
        if para in seen_paragraphs:
            continue
        seen_paragraphs.add(para)
        cleaned_paragraphs.append(para)
    body = '\n\n'.join(cleaned_paragraphs).strip()

    # Generate a hash to detect duplicate content
    content_hash = hashlib.md5(body.encode()).hexdigest()[:12]

    # Get current JST time for the essay date
    jst_now = get_jst_now()

    result = {
        'title': title or f"今日のダーリン - {jst_now.strftime('%Y年%m月%d日')}",
        'author': author or "糸井重里",
        'body': body,
        'date': format_iso_utc(jst_now),
        'jst_date': jst_now.strftime('%Y-%m-%d'),
        'hash': content_hash,
    }

    log.info(f"Essay scraped successfully: {result['title'][:50]}...")
    log.info(f"Content hash: {content_hash}")

    return result


# =============================================================================
# Translation Functions (preserved from V1)
# =============================================================================

def translate_text(japanese_text: str, is_title: bool = False) -> str:
    """
    Translate text using Claude API.

    For body text, returns translation with <p> tags (for feed).
    For titles, returns plain text.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    client = Anthropic(api_key=api_key)

    if is_title:
        prompt = f"""Translate this Japanese essay title into natural English.
Use sentence case (only capitalize the first word), not Title Case.
Output only the translated title, nothing else.

{japanese_text}"""
    else:
        prompt = f"""You are translating a Japanese personal essay into natural, literary English.
Do not translate word-for-word. Your goal is to preserve the author's original voice, tone, and nuance for a native English reader.
Do not include boilerplate like 'Here is the translation.' Do not explain your output.

Preserve paragraph breaks (blank lines = new paragraph). Group related lines into coherent paragraphs.
Render "ほぼ日刊イトイ新聞" or "ほぼ日" as "Hobonichi".
Avoid using em-dashes (—). Use commas, periods, or other punctuation instead.
When the author references specific sounds, phonemes, or the音 (sound) of Japanese words:
- Do NOT attempt to preserve Japanese phonetics in English (no romanisation like "yo" or "su yo")
- Instead, describe what's happening conceptually ("partway through the phrase", "at the end of the sentence")
- Only preserve the actual semantic content of what's being said, not the sound pattern
- If the sound itself is critical to meaning and untranslatable, briefly note this in natural English ("the way the word trails off", "that particular syllable")

Output each paragraph wrapped in <p></p> tags. Output ONLY the <p> tags, no other markup.

{japanese_text}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text
    except APIError as e:
        log.error(f"Claude API error: {e}")
        raise


def summarize_translation(translation: str) -> str:
    """Generate a 1-2 line summary from the translated essay."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    client = Anthropic(api_key=api_key)

    prompt = f"""Create a brief 1-2 sentence summary of this essay that captures its main theme or insight.
Be concise and natural. Output only the summary, nothing else.

{translation}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text.strip()
    except APIError as e:
        log.error(f"Claude API error during summarization: {e}")
        raise


# =============================================================================
# Markdown Export Functions (NEW in V2)
# =============================================================================

def strip_html_tags(html_text: str) -> str:
    """
    Strip <p> and </p> tags from translation, joining paragraphs with double newlines.
    """
    # Remove <p> tags
    text = re.sub(r'<p>', '', html_text)
    # Replace </p> with double newlines
    text = re.sub(r'</p>', '\n\n', text)
    # Clean up extra whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def save_original_markdown(essay: dict) -> bool:
    """
    Save the original Japanese essay as markdown.

    File: originals/TD-Original-YYYY-MM-DD.md
    """
    try:
        ORIGINALS_DIR.mkdir(exist_ok=True)

        jst_date = essay.get('jst_date', get_jst_date_string())
        filename = f"TD-Original-{jst_date}.md"
        filepath = ORIGINALS_DIR / filename

        content = f"""## Title: {essay['title']}
## Date: {jst_date}
## Author: {essay['author']}
## Content:

{essay['body']}
"""

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        log.info(f"Saved original markdown: {filename}")
        return True
    except Exception as e:
        log.error(f"Failed to save original markdown: {e}")
        return False


def save_translated_markdown(essay: dict) -> bool:
    """
    Save the translated English essay as markdown.

    File: translated/TD-Translated-YYYY-MM-DD.md
    Strips <p> tags from translation for clean markdown.
    """
    try:
        TRANSLATED_DIR.mkdir(exist_ok=True)

        jst_date = essay.get('jst_date', get_jst_date_string())
        filename = f"TD-Translated-{jst_date}.md"
        filepath = TRANSLATED_DIR / filename

        # Strip HTML tags for markdown output
        clean_translation = strip_html_tags(essay['translation'])

        content = f"""## Title: {essay.get('translated_title', essay['title'])}
## Date: {jst_date}
## Author: {essay.get('translated_author', essay['author'])}
## Content:

{clean_translation}
"""

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        log.info(f"Saved translated markdown: {filename}")
        return True
    except Exception as e:
        log.error(f"Failed to save translated markdown: {e}")
        return False


# =============================================================================
# Archive Functions (preserved from V1)
# =============================================================================

def load_archive() -> list:
    """Load existing archive of essays."""
    if ARCHIVE_FILE.exists():
        with open(ARCHIVE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_archive(archive: list):
    """Save archive to disk."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(ARCHIVE_FILE, 'w', encoding='utf-8') as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)
    log.info(f"Archive saved with {len(archive)} entries")


# =============================================================================
# Feed Generation (preserved from V1)
# =============================================================================

def generate_atom(archive: list):
    """Generate Atom feed from archive."""
    fg = FeedGenerator()
    fg.id('https://adtheriault.github.io/todays-darling/atom.xml')
    fg.title("Today's Darling")
    fg.subtitle('Daily essays by Shigesato Itoi from 1101.com, translated to English.')
    # Point to GitHub Pages root as the permanent home
    fg.link(href=PAGES_BASE_URL, rel='alternate', type='text/html')
    fg.link(href='https://adtheriault.github.io/todays-darling/atom.xml', rel='self', type='application/atom+xml')
    # Attribution link to original source
    fg.link(href=SOURCE_URL, rel='via', type='text/html', hreflang='ja')
    fg.language('en')
    fg.icon(HOBONICHI_ICON_URL)

    # Add entries (feedgen reverses order, so add oldest first to get newest first in output)
    sorted_entries = sorted(archive[:30], key=lambda x: x['date'], reverse=False)
    for entry_data in sorted_entries:
        fe = fg.add_entry()
        entry_url = f"https://adtheriault.github.io/todays-darling/#{entry_data['hash']}"
        fe.id(entry_url)
        fe.title(entry_data.get('translated_title', entry_data['title']))
        fe.author({'name': entry_data.get('translated_author', entry_data.get('author', 'Shigesato Itoi'))})
        # Permanent URL pointing to the entry in our archive
        fe.link(href=entry_url, rel='alternate', type='text/html')
        # Attribution link to original source
        fe.link(href=SOURCE_URL, rel='via', type='text/html', hreflang='ja')

        # Use summary for description (1-2 line summary)
        summary = entry_data.get('summary', '')
        fe.summary(summary)

        # Add full translation as content with centered header image
        translation = entry_data['translation']
        # Prepend a centered image at the top of the content
        image_html = f'<div style="text-align: center; margin-bottom: 20px;"><img src="{DARLING_IMAGE_URL}" alt="Hobonichi Darling" style="max-width: 300px; height: auto;"/></div>'
        content_with_image = image_html + translation
        fe.content(content=content_with_image, type='html')

        fe.published(entry_data['date'])
        fe.updated(entry_data['date'])

    OUTPUT_DIR.mkdir(exist_ok=True)
    fg.atom_file(str(FEED_FILE), pretty=True)

    # Post-process to match the desired header format
    with open(FEED_FILE, 'r', encoding='utf-8') as f:
        xml_content = f.read()

    # Add thr and media namespaces if not present
    if 'xmlns:media=' not in xml_content:
        xml_content = xml_content.replace(
            '<feed xmlns="http://www.w3.org/2005/Atom"',
            '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/" xmlns:thr="http://purl.org/syndication/thread/1.0"',
            1
        )
    elif 'xmlns:thr=' not in xml_content:
        xml_content = xml_content.replace(
            '<feed xmlns="http://www.w3.org/2005/Atom"',
            '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:thr="http://purl.org/syndication/thread/1.0"',
            1
        )

    # Add type="text" to title element
    if '<title type=' not in xml_content:
        xml_content = xml_content.replace(
            '<title>',
            '<title type="text">',
            1
        )

    # Reorder feed header elements to match convention:
    # title, subtitle, updated, link(alternate), id, link(self), icon
    feed_match = re.search(r'<feed[^>]*>.*?(?=<entry|</feed>)', xml_content, re.DOTALL)
    if feed_match:
        feed_section = feed_match.group(0)

        # Extract individual elements
        title_match = re.search(r'(<title[^>]*>.*?</title>)', feed_section)
        subtitle_match = re.search(r'(<subtitle>.*?</subtitle>)', feed_section)
        updated_match = re.search(r'(<updated>.*?</updated>)', feed_section)
        links = re.findall(r'(<link[^>]*/?>)', feed_section)
        id_match = re.search(r'(<id>.*?</id>)', feed_section)
        icon_match = re.search(r'(<icon>.*?</icon>)', feed_section)

        # Reconstruct in desired order with all namespaces
        new_feed = '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/" xmlns:thr="http://purl.org/syndication/thread/1.0" xml:lang="en">\n'
        if title_match:
            new_feed += '  ' + title_match.group(1) + '\n'
        if subtitle_match:
            new_feed += '  ' + subtitle_match.group(1) + '\n'
        if updated_match:
            new_feed += '  ' + updated_match.group(1) + '\n'
        # Add links in order: alternate first, then self
        for link in links:
            if 'rel="alternate"' in link:
                new_feed += '  ' + link + '\n'
        if id_match:
            new_feed += '  ' + id_match.group(1) + '\n'
        for link in links:
            if 'rel="self"' in link:
                new_feed += '  ' + link + '\n'
        if icon_match:
            new_feed += '  ' + icon_match.group(1) + '\n'

        # Replace the feed opening with our reconstructed one
        xml_content = new_feed + xml_content[feed_match.end():]

    # Add media:thumbnail to each entry
    for entry_data in archive[:30]:
        guid = entry_data['hash']
        entry_id_pattern = f'<id>https://adtheriault.github.io/todays-darling/#{guid}</id>'
        if entry_id_pattern in xml_content:
            # Add thumbnail after the published element
            thumbnail_tag = f'<media:thumbnail url="{DARLING_IMAGE_URL}" width="200" height="144"/>'
            published_pattern = '</published>'
            # Find the published tag that comes after this entry's id
            entry_start = xml_content.find(entry_id_pattern)
            if entry_start != -1:
                # Find the next </published> after this entry
                published_end = xml_content.find(published_pattern, entry_start)
                if published_end != -1:
                    insertion_point = published_end + len(published_pattern)
                    # Check if thumbnail already exists for this entry
                    check_range = xml_content[entry_start:entry_start + 1500]
                    if '<media:thumbnail' not in check_range:
                        xml_content = xml_content[:insertion_point] + '\n  ' + thumbnail_tag + xml_content[insertion_point:]

    # Write final XML
    with open(FEED_FILE, 'w', encoding='utf-8') as f:
        f.write(xml_content)

    log.info(f"Atom feed generated: {FEED_FILE}")


# =============================================================================
# Main Processing Logic
# =============================================================================

def process_essay() -> bool:
    """
    Main processing pipeline: scrape -> translate -> archive -> feed.

    Returns True on success, False on failure.
    """
    # Step 1: Scrape essay
    essay = scrape_essay()
    if not essay:
        log.error("No essay found")
        return False

    # Step 2: Check for duplicates (JSON is source of truth)
    archive = load_archive()
    existing_hashes = {e['hash'] for e in archive}

    if essay['hash'] in existing_hashes:
        log.info(f"Essay already archived (hash: {essay['hash']}), skipping")
        # Still regenerate feed in case it's missing
        generate_atom(archive)
        return True  # Not a failure, just already processed

    # Step 3: Save original markdown (before translation)
    if not save_original_markdown(essay):
        log.warning("Failed to save original markdown, continuing anyway")

    # Step 4: Translate
    log.info("Translating title...")
    translated_title = translate_text(essay['title'], is_title=True).strip()

    log.info("Translating author...")
    translated_author = translate_text(essay['author'], is_title=True).strip()

    log.info("Translating essay body...")
    translation = translate_text(essay['body'])

    log.info("Generating summary...")
    summary = summarize_translation(translation)

    # Step 5: Update essay with translations
    essay['translation'] = translation
    essay['summary'] = summary
    essay['translated_title'] = translated_title
    essay['translated_author'] = translated_author

    # Step 6: Save translated markdown (after translation)
    if not save_translated_markdown(essay):
        log.warning("Failed to save translated markdown, continuing anyway")

    # Step 7: Update JSON archive
    archive.insert(0, essay)  # Most recent first
    save_archive(archive)

    # Step 8: Generate Atom feed
    generate_atom(archive)

    log.info(f"Successfully processed: {essay['title']}")
    log.info(f"Translated title: {translated_title}")
    log.info(f"Summary: {summary}")

    return True


def run_with_retry(max_attempts: int = 3, retry_delay_hours: float = 2.0) -> bool:
    """
    Run the scraper with retry logic.

    Args:
        max_attempts: Maximum number of attempts (default 3)
        retry_delay_hours: Hours to wait between retries (default 2)

    Returns True if successful on any attempt.

    Note: In GitHub Actions, retries are typically handled via separate
    cron schedules rather than in-process delays. This function is provided
    for local testing and as a fallback.
    """
    import time

    for attempt in range(1, max_attempts + 1):
        log.info(f"=== Attempt {attempt}/{max_attempts} ===")

        try:
            if process_essay():
                log.info(f"Success on attempt {attempt}")
                return True
        except Exception as e:
            log.error(f"Attempt {attempt} failed with error: {e}")
            import traceback
            log.error(traceback.format_exc())

        if attempt < max_attempts:
            delay_seconds = retry_delay_hours * 3600
            log.info(f"Waiting {retry_delay_hours} hours before retry...")
            # In practice, GitHub Actions handles scheduling
            # This is mainly for local testing
            if os.environ.get('LOCAL_RETRY_ENABLED'):
                time.sleep(delay_seconds)
            else:
                log.info("Exiting (retries handled by GitHub Actions schedule)")
                return False

    log.error(f"All {max_attempts} attempts failed")
    return False


def main():
    """Entry point for the scraper."""
    log.info("=" * 60)
    log.info("Hobonichi Scraper V2")
    log.info(f"Current time (JST): {get_jst_now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    # Check for required environment variable
    if not os.environ.get('ANTHROPIC_API_KEY'):
        log.error("ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)

    # Run the scraper
    success = process_essay()

    if success:
        log.info("Scraper completed successfully")
        sys.exit(0)
    else:
        log.error("Scraper failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
