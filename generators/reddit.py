# generators/reddit.py

import os
import gzip
import random
import re
import time
import requests
from datetime import datetime

# --- Constants ---
DOMAIN_NAME = "reddit"
# A fallback list in case the download fails
FALLBACK_STOP_WORDS = set([
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'in', 'on', 'at', 'to', 'for',
    'of', 'and', 'or', 'but', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'what',
    'who', 'when', 'where', 'why', 'how', 'that', 'this', 'from', 'with', 'have',
    'has', 'had', 'do', 'does', 'did', 'not', 'no', 'be', 'been', 'about', 'like',
    'just', 'get', 'out', 'up', 'down', 'all', 'com', 'www', 'https', 'http',
    'thanks', 'welcome', 'companion', 'bosnian'
])
COMMON_WORDS_URL = "https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt"
COMMON_WORDS_CACHE_PATH = "common_english_words.txt.gz"

# --- Helper Functions ---

def load_common_words(console):
    """
    Loads a large set of common English words, caching it locally.
    """
    if os.path.exists(COMMON_WORDS_CACHE_PATH):
        with gzip.open(COMMON_WORDS_CACHE_PATH, 'r') as f:
            return set(line.strip().lower() for line in f)

    try:
        console.log(f"Downloading common words list from {COMMON_WORDS_URL}...")
        response = requests.get(COMMON_WORDS_URL)
        response.raise_for_status()
        words = [line.lower() for line in response.text.splitlines()]
        with open(COMMON_WORDS_CACHE_PATH, 'w') as f:
            f.write("\n".join(words))
        console.log(f"Cached {len(words)} common words to '{COMMON_WORDS_CACHE_PATH}'.")
        return set(words)
    except requests.exceptions.RequestException as e:
        console.log(f"[yellow]Warning: Could not download common words list: {e}[/yellow]")
        console.log("[yellow]Falling back to a small, built-in stop word list.[/yellow]")
        return FALLBACK_STOP_WORDS

def get_headers():
    """Returns standard headers for Reddit API requests."""
    return {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 15.6; rv:141.0) Gecko/20100101 Firefox/141.0"}

def find_obscure_posts():
    """
    Finds obscure posts on Reddit by searching for niche terms and filtering by low score.
    Returns the posts and the search query used.
    """
    search_terms = [
        "procedural generation", "vintage computing", "sffpc", "home server",
        "mechanical keyboards", "fountain pens", "geocaching", "lockpicking",
        "mycology", "solarpunk", "worldbuilding", "urban exploration", "roguelikedev"
    ]
    query = random.choice(search_terms)
    url = f"https://www.reddit.com/search.json?q={query}&sort=new&limit=100&t=all&type=link&score=0..5"

    try:
        response = requests.get(url, headers=get_headers())
        response.raise_for_status()
        posts = response.json().get("data", {}).get("children", [])
        filtered_posts = [
            p['data'] for p in posts
            if p.get('data', {}).get('num_comments', 0) > 0 and not p.get('data', {}).get('subreddit', '').lower() in ['askreddit', 'funny']
        ]
        return filtered_posts, query
    except requests.exceptions.RequestException as e:
        print(f"Error fetching posts from Reddit: {e}")
        return [], None

def get_all_comments_and_keywords(posts, common_words_set):
    """
    Iterates through posts, fetches comments, and extracts all valid keywords.
    Returns a list of (comment_object, keyword_list) tuples and a flat list of all keywords.
    """
    all_keywords = []
    comment_keyword_map = []

    for post in posts:
        permalink = post.get('permalink')
        if not permalink:
            continue

        # Fetch comments for the post
        if not permalink.endswith('.json'):
            permalink += ".json"
        url = f"https://www.reddit.com{permalink}"
        try:
            response = requests.get(url, headers=get_headers())
            response.raise_for_status()
            comments_data = response.json()[1].get("data", {}).get("children", [])
        except (requests.exceptions.RequestException, IndexError, KeyError):
            continue

        for comment_data in comments_data:
            comment = comment_data.get('data', {})
            body = comment.get('body', '').strip()
            if 20 < len(body) < 400 and body != '[deleted]' and body != '[removed]':
                words = set(re.findall(r'\b\w+\b', body.lower()))
                uncommon_words = [w for w in words if w not in common_words_set and len(w) > 6]
                if uncommon_words:
                    comment_keyword_map.append((comment, uncommon_words))
                    all_keywords.extend(uncommon_words)
        print(f"fetched {permalink}")
        time.sleep(1.2) # Be nice to Reddit's API

    return comment_keyword_map, list(set(all_keywords))

# --- Main Generator Function ---

def generate(count, console, verify_uniqueness):
    """
    Generates a list of unique question-answer pairs from obscure Reddit comments.
    """
    qa_pairs = []

    common_words_set = load_common_words(console)

    console.log("Searching for obscure posts on Reddit...")
    posts, topic = find_obscure_posts()
    if not posts or not topic:
        console.log("[red]Could not find any suitable posts on Reddit.[/red]")
        return []

    console.log("Aggregating comments and keywords...")
    comment_keyword_map, all_uncommon_keywords = get_all_comments_and_keywords(posts, common_words_set)

    if not comment_keyword_map or not all_uncommon_keywords:
        console.log("[red]Found posts but could not extract any suitable comments or keywords.[/red]")
        return []

    console.log(f"Found {len(comment_keyword_map)} candidate comments and {len(all_uncommon_keywords)} unique keywords.")

    while len(qa_pairs) < count and comment_keyword_map:

        # Pick a random comment to be the subject of the question
        comment_obj, true_keywords = random.choice(comment_keyword_map)
        true_keyword = random.choice(true_keywords)
        source_url = "https://www.reddit.com" + comment_obj['permalink']

        # Decide whether to make a 'Yes' or 'No' question
        if random.random() < 0.5:
            # --- YES CASE ---
            question_keyword = true_keyword
            answer = "Yes"
        else:
            # --- NO CASE (Fake-out) ---
            # Find a keyword that is NOT in the current comment's true keywords
            fake_keyword = random.choice(all_uncommon_keywords)
            while fake_keyword in true_keywords:
                fake_keyword = random.choice(all_uncommon_keywords)
            question_keyword = fake_keyword
            answer = "No"

        console.log(f"  -> Generating '{answer}' question for comment {comment_obj['id']} with keyword '{question_keyword}'")

        # For this type of question, uniqueness verification is less critical, but we can still run it.
        verification = verify_uniqueness(f'"{question_keyword}" "{topic}"', source_url)

        question = f"Does the Reddit comment at the URL {source_url} contain the word '{question_keyword}'? Answer Yes or No."

        qa_pairs.append({
            "id": f"{DOMAIN_NAME}-{comment_obj['id']}-{random.randint(1000,9999)}",
            "domain": DOMAIN_NAME,
            "source_url": source_url,
            "question": question,
            "answer": answer,
            "eval_method": "string_match",
            "generation_metadata": {
                "topic": topic,
                "subreddit": comment_obj['subreddit'],
                "question_type": answer, # "Yes" or "No"
                "keyword_tested": question_keyword,
                "created_utc": datetime.utcfromtimestamp(comment_obj['created_utc']).isoformat() + "Z",
                "verification_details": verification
            }
        })

    return qa_pairs
