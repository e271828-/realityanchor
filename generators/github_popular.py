# generators/github_popular.py

import os
import random
import re
import time
import requests
from datetime import datetime

# --- Constants ---
DOMAIN_NAME = "github_popular"
GITHUB_API_TOKEN = os.environ.get("GITHUB_API_TOKEN", None) # Optional, but increases rate limit

# --- Helper Functions ---

def get_headers():
    """Returns headers for GitHub API requests."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_API_TOKEN:
        headers["Authorization"] = f"token {GITHUB_API_TOKEN}"
    return headers

def find_popular_repos():
    """
    Finds popular GitHub repositories with a high star count.
    """
    # Search for repos with >5000 stars, pushed to in the last couple of years.
    query = "stars:>5000 pushed:>2023-01-01 language:python language:javascript language:ruby language:go language:php"
    # Sort by most recently updated to get fresh results
    url = f"https://api.github.com/search/repositories?q={query}&sort=updated&order=desc&per_page=100"

    try:
        response = requests.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json().get("items", [])
    except requests.exceptions.RequestException as e:
        print(f"Error fetching popular repos from GitHub: {e}")
        return []

def get_repo_files(repo_full_name):
    """
    Recursively fetches all file paths in a repository.
    """
    for branch in ['main', 'master', 'dev']: # Popular repos might use 'dev'
        url = f"https://api.github.com/repos/{repo_full_name}/git/trees/{branch}?recursive=1"
        try:
            response = requests.get(url, headers=get_headers())
            response.raise_for_status()
            data = response.json()
            # Filter out directories and common non-code/test files
            files = [
                item['path'] for item in data.get('tree', [])
                if item['type'] == 'blob' and 'test' not in item['path'].lower() and not item['path'].endswith(('.md', '.png', '.lock', '.json'))
            ]
            if files:
                return files, branch
        except requests.exceptions.RequestException:
            continue
    return [], None

def extract_variable_and_value(content):
    """
    Extracts variable assignments from file content, looking for non-trivial values.
    """
    regex = re.compile(
        r"""
        ([a-zA-Z_][a-zA-Z0-9_]{4,}) # Group 1: Variable name (at least 5 chars)
        \s*[:=]\s* # Assignment operator
        (['"`])                     # Group 2: Opening quote
        (.*?)                       # Group 3: The actual value
        \2                          # Match the same closing quote
        """, re.VERBOSE
    )

    lines = content.split('\n')
    candidates = []

    for line in lines:
        match = regex.search(line)
        if match:
            variable_name = match.group(1)
            value = match.group(3)

            # Filter for specific, non-generic values
            if 5 < len(value) < 100 and not value.startswith('http') and re.search(r'[a-zA-Z]', value):
                candidates.append((variable_name, value))

    if not candidates:
        return None

    return random.choice(candidates)

# --- Main Generator Function ---

def generate(count, console, verify_uniqueness):
    """
    Generates a list of unique question-answer pairs from popular GitHub repos.
    """
    qa_pairs = []

    console.log("Searching for popular repositories on GitHub...")
    repos = find_popular_repos()
    if not repos:
        console.log("[red]Could not find any suitable popular repositories.[/red]")
        return []

    random.shuffle(repos)

    repo_search_limit = 100
    checked_repos = 0

    for repo in repos:
        if len(qa_pairs) >= count or checked_repos >= repo_search_limit:
            break

        checked_repos += 1
        repo_name = repo['full_name']

        files, branch_name = get_repo_files(repo_name)
        if not files:
            continue

        console.log(f"  -> Probing repo: [cyan]{repo_name}[/cyan] ({repo['stargazers_count']} stars)")

        for _ in range(min(5, len(files))): # Try up to 5 random files
            random_file_path = random.choice(files)
            file_url = f"https://api.github.com/repos/{repo_name}/contents/{random_file_path}"

            try:
                media_headers = get_headers()
                media_headers['Accept'] = 'application/vnd.github.raw'
                file_response = requests.get(file_url, params={'ref': branch_name}, headers=media_headers)
                file_response.raise_for_status()
                content = file_response.text
            except (requests.exceptions.RequestException, UnicodeDecodeError):
                continue

            candidate = extract_variable_and_value(content)
            if not candidate:
                continue

            variable_name, value = candidate
            source_url = repo['html_url'] + f'/blob/{branch_name}/' + random_file_path

            console.log(f"    - Verifying candidate var '{variable_name}' from '{random_file_path}'...")
            verification = verify_uniqueness(f'"{value}" "{repo_name}"', source_url)

            if verification["is_unique"]:
                console.log(f"    [green]Found unique value in popular repo![/green]")

                question = f"In the popular GitHub repository '{repo_name}', what is the value of the variable named `{variable_name}` found in the file at {source_url}?"

                qa_pairs.append({
                    "id": f"{DOMAIN_NAME}-{repo['id']}-{random.randint(1000, 9999)}",
                    "domain": DOMAIN_NAME,
                    "source_url": source_url,
                    "question": question,
                    "answer": value,
                    "eval_method": "string_match",
                    "generation_metadata": {
                        "repo_name": repo_name,
                        "file_path": random_file_path,
                        "variable_name": variable_name,
                        "stars": repo.get('stargazers_count', 0),
                        "pushed_at": repo.get('pushed_at'),
                        "verification_details": verification
                    }
                })

                break

        time.sleep(1.5)

    return qa_pairs
