# generators/wikipedia.py

import os
import random
import re
import time
import requests
from datetime import datetime

# --- Constants ---
DOMAIN_NAME = "wikipedia"
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
COMMON_WORDS_CACHE_PATH = "common_english_words.txt" # Assumes it's downloaded by the Reddit generator

# --- Helper Functions ---

def load_common_words(console):
    """
    Loads a large set of common English words from the local cache.
    Assumes the Reddit generator has already downloaded it.
    """
    if os.path.exists(COMMON_WORDS_CACHE_PATH):
        with open(COMMON_WORDS_CACHE_PATH, 'r') as f:
            return set(line.strip().lower() for line in f)
    else:
        console.log(f"[yellow]Warning: '{COMMON_WORDS_CACHE_PATH}' not found. Run the Reddit generator first to download it.[/yellow]")
        return set() # Return empty set if not found

def get_pages_from_category(category, console):
    """
    Gets a list of page titles from a given Wikipedia category.
    """
    pages = []
    params = {
        "action": "query",
        "format": "json",
        "list": "categorymembers",
        "cmtitle": category,
        "cmlimit": "500"
    }
    try:
        response = requests.get(WIKIPEDIA_API_URL, params=params, headers={"User-Agent": "RealityAnchorBenchmark/0.1"})
        response.raise_for_status()
        data = response.json().get("query", {}).get("categorymembers", [])
        for member in data:
            if member.get('ns') == 0:
                 pages.append(member['title'])
        return pages
    except requests.exceptions.RequestException as e:
        console.log(f"[red]Error fetching pages from Wikipedia category '{category}': {e}[/red]")
        return []

def get_article_first_sentence(page_title, console):
    """
    Fetches the plain text introduction of a Wikipedia article and returns the first sentence.
    """
    params = {
        "action": "query",
        "prop": "extracts|revisions",
        "exintro": True,
        "explaintext": True,
        "format": "json",
        "titles": page_title,
        "redirects": 1
    }
    try:
        response = requests.get(WIKIPEDIA_API_URL, params=params, headers={"User-Agent": "RealityAnchorBenchmark/0.1"})
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {})
        if not pages: return None, None

        page_id = list(pages.keys())[0]
        if page_id == "-1": return None, None

        page_data = pages[page_id]
        extract = page_data.get("extract", "")
        timestamp = page_data.get("revisions", [{}])[0].get("timestamp")

        if not extract:
            return None, None

        first_sentence = extract.split('.')[0].strip() + "."

        if len(first_sentence) > 25 and len(first_sentence) < 400 and "may refer to" not in first_sentence.lower():
            return first_sentence, timestamp

        return None, None

    except requests.exceptions.RequestException:
        return None, None

# --- Main Generator Function ---

def generate(count, console, verify_uniqueness):
    """
    Generates a list of unique question-answer pairs from obscure Wikipedia articles.
    """
    qa_pairs = []

    common_words_set = load_common_words(console)

    niche_categories = [
        "Category:Defunct software companies of the United States",
        "Category:Geological phenomena", "Category:Units of time",
        "Category:Astronomical catalogues", "Category:19th-century inventions"
    ]
    random.shuffle(niche_categories)

    pages = []
    for category in niche_categories:
        console.log(f"Attempting to fetch pages from Wikipedia category: [cyan]{category}[/cyan]")
        pages = get_pages_from_category(category, console)
        if pages:
            console.log(f"Found {len(pages)} pages.")
            break

    if not pages:
        console.log("[red]Could not find any pages after trying multiple categories.[/red]")
        return []

    random.shuffle(pages)

    article_sentence_map = {}
    all_uncommon_words = set()

    checked_pages = 0
    probe_limit = 50

    console.log("Probing random articles to build a sentence map...")
    for page_title in pages:
        if checked_pages >= probe_limit: break
        checked_pages += 1

        console.log(f"  -> Probing article ({checked_pages}/{probe_limit}): [cyan]{page_title}[/cyan]")
        sentence, last_modified = get_article_first_sentence(page_title, console)

        if sentence and last_modified:
            words = set(re.findall(r'\b\w+\b', sentence.lower()))
            normalized_title = page_title.lower()
            # Filter out words that are common OR appear in the article's title
            uncommon_words = [
                w for w in words
                if w not in common_words_set and len(w) > 6 and w not in normalized_title
            ]
            if uncommon_words:
                article_sentence_map[page_title] = {
                    "sentence": sentence,
                    "uncommon_words": uncommon_words,
                    "last_modified": last_modified
                }
                all_uncommon_words.update(uncommon_words)
        time.sleep(1.2)

    if not article_sentence_map or not all_uncommon_words:
        console.log("[red]Failed to build a map of articles with valid sentences and keywords.[/red]")
        return []

    console.log(f"Built map with {len(article_sentence_map)} articles and {len(all_uncommon_words)} unique keywords.")
    all_uncommon_words = list(all_uncommon_words)
    articles_with_sentences = list(article_sentence_map.keys())

    while len(qa_pairs) < count and articles_with_sentences:
        page_title = random.choice(articles_with_sentences)
        article_data = article_sentence_map[page_title]

        # Ensure the article still has valid uncommon words after filtering
        if not article_data["uncommon_words"]:
            continue

        if random.random() < 0.5:
            # --- YES CASE ---
            question_word = random.choice(article_data["uncommon_words"])
            answer = "Yes"
        else:
            # --- NO CASE (Fake-out) ---
            normalized_title = page_title.lower()
            fake_word = random.choice(all_uncommon_words)
            # Ensure the fake word is not in the true keywords AND not in the title
            while fake_word in article_data["uncommon_words"] or fake_word in normalized_title:
                fake_word = random.choice(all_uncommon_words)
            question_word = fake_word
            answer = "No"

        console.log(f"  -> Generating '{answer}' question for article '{page_title}' with word '{question_word}'")

        question = f"Does the first sentence of the English Wikipedia article for '{page_title}' contain the word '{question_word}'? Answer Yes or No."
        source_url = f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}"

        qa_pairs.append({
            "id": f"{DOMAIN_NAME}-{page_title.replace(' ', '_')}-{random.randint(1000,9999)}",
            "domain": DOMAIN_NAME,
            "source_url": source_url,
            "question": question,
            "answer": answer,
            "eval_method": "string_match",
            "generation_metadata": {
                "article_title": page_title,
                "question_type": answer,
                "word_tested": question_word,
                "last_modified_utc": article_data["last_modified"],
            }
        })

    return qa_pairs
