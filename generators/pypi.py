# generators/pypi.py

import os
import random
import re
import time
import requests
from datetime import datetime

# --- Constants ---
DOMAIN_NAME = "pypi"

# --- Helper Functions ---

def find_all_packages(console):
    """
    Finds packages by fetching the full list from PyPI's simple index.
    This is much more robust than scraping search results.
    """
    url = "https://pypi.org/simple/"
    try:
        console.log(f"Attempting to fetch the full package list from {url}...")
        response = requests.get(url, headers={"User-Agent": "RealityAnchorBenchmark/0.1"})
        response.raise_for_status()

        package_names = re.findall(r'<a href="/simple/([^/]+)/"', response.text)

        if package_names:
            console.log(f"Successfully fetched {len(package_names)} package names.")
            return package_names

    except requests.exceptions.RequestException as e:
        console.log(f"[red]Fatal error fetching full package list from PyPI: {e}[/red]")

    return []

def get_package_metadata(package_name):
    """Fetches the full JSON metadata for a specific package."""
    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        response = requests.get(url, headers={"User-Agent": "RealityAnchorBenchmark/0.1"})
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        return None

def get_package_requirements(info):
    """Extracts a clean list of requirements from package info."""
    reqs = info.get("requires_dist", []) or []
    # Filter for simple requirements with version specifiers
    return [r for r in reqs if r and ";" not in r and ("=" in r or ">" in r or "<" in r)]

# --- Main Generator Function ---

def generate(count, console, verify_uniqueness):
    """
    Generates a list of unique question-answer pairs from obscure PyPI packages.
    """
    qa_pairs = []

    all_packages = find_all_packages(console)
    if not all_packages:
        console.log("[red]Could not retrieve the package list from PyPI.[/red]")
        return []

    random.shuffle(all_packages)

    package_requirements_map = {}
    all_known_requirements = set()

    checked_packages = 0
    # We need to probe a good number to build our "fake-out" list
    probe_limit = 200

    console.log("Probing random packages to build a requirement map...")
    for pkg_name in all_packages:
        if checked_packages >= probe_limit:
            break

        checked_packages += 1

        if checked_packages % 20 == 0:
             console.log(f"Probed {checked_packages}/{probe_limit} packages...")
             time.sleep(1)

        metadata = get_package_metadata(pkg_name)
        if not metadata:
            continue

        info = metadata.get("info", {})

        # We only care about packages that have requirements
        requirements = get_package_requirements(info)
        if requirements:
            package_requirements_map[pkg_name] = {
                "requirements": requirements,
                "source_url": info.get("package_url"),
                "created_utc": min(
                    f['upload_time_iso_8601'] for r in metadata.get("releases", {}).values() if r for f in r
                )
            }
            all_known_requirements.update(requirements)

    if not package_requirements_map or not all_known_requirements:
        console.log("[red]Failed to build a map of packages with requirements.[/red]")
        return []

    console.log(f"Built map with {len(package_requirements_map)} packages and {len(all_known_requirements)} unique requirements.")
    all_known_requirements = list(all_known_requirements)

    package_names_with_reqs = list(package_requirements_map.keys())

    while len(qa_pairs) < count and package_names_with_reqs:
        pkg_name = random.choice(package_names_with_reqs)
        pkg_data = package_requirements_map[pkg_name]

        # Decide whether to make a 'Yes' or 'No' question
        if random.random() < 0.5:
            # --- YES CASE ---
            question_req = random.choice(pkg_data["requirements"])
            answer = "Yes"
        else:
            # --- NO CASE (Fake-out) ---
            fake_req = random.choice(all_known_requirements)
            while fake_req in pkg_data["requirements"]:
                fake_req = random.choice(all_known_requirements)
            question_req = fake_req
            answer = "No"

        console.log(f"  -> Generating '{answer}' question for package '{pkg_name}' with requirement '{question_req}'")

        question = f"According to its PyPI listing, does the package '{pkg_name}' have a direct requirement for '{question_req}'? Answer Yes or No."

        qa_pairs.append({
            "id": f"{DOMAIN_NAME}-{pkg_name}-{random.randint(1000,9999)}",
            "domain": DOMAIN_NAME,
            "source_url": pkg_data["source_url"],
            "question": question,
            "answer": answer,
            "eval_method": "string_match",
            "generation_metadata": {
                "package_name": pkg_name,
                "question_type": answer,
                "requirement_tested": question_req,
                "created_utc": pkg_data["created_utc"],
            }
        })

    return qa_pairs
