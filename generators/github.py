# generators/github.py

import os
import random
import re
import time
import requests
from datetime import datetime

# --- Constants ---
DOMAIN_NAME = "github"
GITHUB_API_TOKEN = os.environ.get("GITHUB_API_TOKEN", None) # Optional, but increases rate limit

# --- Helper Functions ---

def get_headers():
    """Returns headers for GitHub API requests."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_API_TOKEN:
        headers["Authorization"] = f"token {GITHUB_API_TOKEN}"
    return headers

def find_obscure_repos():
    """
    Finds GitHub repositories with 0 or 1 stars, created some time ago.
    This increases the chance that the content is stable and not brand new.
    """
    # Search for repos with 0 or 1 star, pushed to more than a year ago
    # We also add a language filter to focus on text-based files.
    query = "stars:0..1 pushed:<2023-01-01 language:python language:javascript language:ruby language:go language:php"
    # Randomize the sort to get different results each time
    sort_options = ["stars", "forks", "updated"]
    url = f"https://api.github.com/search/repositories?q={query}&sort={random.choice(sort_options)}&order=asc&per_page=100"
    
    try:
        response = requests.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json().get("items", [])
    except requests.exceptions.RequestException as e:
        print(f"Error fetching repos from GitHub: {e}")
        return []

def get_repo_files(repo_full_name):
    """
    Recursively fetches all file paths in a repository.
    """
    # The default branch is not always 'main'. We can try 'master' as a fallback.
    for branch in ['main', 'master']:
        url = f"https://api.github.com/repos/{repo_full_name}/git/trees/{branch}?recursive=1"
        try:
            response = requests.get(url, headers=get_headers())
            response.raise_for_status()
            data = response.json()
            # Filter out directories and common non-code files
            files = [
                item['path'] for item in data.get('tree', []) 
                if item['type'] == 'blob' and not item['path'].endswith(('.png', '.jpg', '.gif', '.lock'))
            ]
            if files:
                return files, branch # Return files and the branch name
        except requests.exceptions.RequestException:
            continue # Try the next branch
    return [], None

def extract_variable_and_value(content):
    """
    Extracts variable assignments from file content.
    Looks for patterns like: var = "value", var: 'value', etc.
    """
    # Regex to find variable names and their string/numeric values.
    # Captures: 1. variable name, 2. quote type, 3. value
    regex = re.compile(
        r"""
        ([a-zA-Z_][a-zA-Z0-9_]{3,}) # Group 1: Variable name (at least 4 chars)
        \s*[:=]\s* # Assignment operator (colon or equals)
        (['"`])                      # Group 2: Opening quote
        (.*?)                       # Group 3: The actual value (non-greedy)
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
            
            # Filter out trivial or common values
            if 5 < len(value) < 100 and value.lower() not in ['true', 'false', 'null', '']:
                candidates.append((variable_name, value))

    if not candidates:
        return None

    # Return a random candidate from the file
    return random.choice(candidates)


# --- Main Generator Function ---

def generate(count, console, verify_uniqueness):
    """
    Generates a list of unique question-answer pairs from obscure GitHub repos.
    """
    qa_pairs = []
    
    console.log("Searching for obscure repositories on GitHub...")
    repos = find_obscure_repos()
    if not repos:
        console.log("[red]Could not find any suitable repositories. Check GitHub API access or query.[/red]")
        return []

    random.shuffle(repos)
    
    repo_search_limit = 100 # Stop after checking this many repos to avoid long runs
    checked_repos = 0

    for repo in repos:
        if len(qa_pairs) >= count or checked_repos >= repo_search_limit:
            break
        
        checked_repos += 1
        repo_name = repo['full_name']
        
        files, branch_name = get_repo_files(repo_name)
        if not files:
            continue
        
        console.log(f"  -> Probing repo: [cyan]{repo_name}[/cyan] ({len(files)} files)")
        
        # Try a few random files from the repo
        for _ in range(min(3, len(files))): # Try up to 3 files
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
            verification = verify_uniqueness(value, source_url)

            if verification["is_unique"]:
                console.log(f"    [green]Found unique value![/green]")
                
                question = f"In the GitHub file at {source_url}, what is the value of the variable named `{variable_name}`?"
                
                qa_pairs.append({
                    "id": f"{DOMAIN_NAME}-{repo['id']}-{random.randint(1000, 9999)}",
                    "domain": DOMAIN_NAME,
                    "source_url": source_url,
                    "question": question,
                    "answer": value, # The exact value is the answer
                    "eval_method": "string_match",
                    "generation_metadata": {
                        "repo_name": repo_name,
                        "file_path": random_file_path,
                        "variable_name": variable_name,
                        "stars": repo.get('stargazers_count', 0),
                        "pushed_at": repo.get('pushed_at'), # Added timestamp
                        "verification_details": verification
                    }
                })
                
                # Found a valid pair, break from the inner file-checking loop
                break
        
        # To avoid hitting rate limits too aggressively
        time.sleep(1.5)

    return qa_pairs
