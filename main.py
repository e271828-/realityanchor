# main.py
import argparse
import json
import os
import importlib
import pkgutil
from datetime import datetime
from rich.console import Console
from rich.table import Table
import requests
import openai
from brave import Brave


# --- Configuration ---
# You can get one from https://brave.com/search/api/
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "YOUR_BRAVE_API_KEY")

# Configure your LLM provider endpoint.
# You can point this to OpenRouter, a local LLM, etc.
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")

BENCHMARKS_DIR = "benchmarks"
console = Console()

# --- Uniqueness Verification ---

def verify_uniqueness(text_to_check: str, source_url: str) -> dict:
    """
    Verifies the uniqueness of a string using the Brave Search API.

    A string is considered "unique" if the search engine returns
    very few results, and the source URL is among them.

    Args:
        text_to_check: The string to search for (e.g., a line of code).
        source_url: The original URL where the string was found.

    Returns:
        A dictionary containing verification results.
    """
    if not BRAVE_API_KEY or BRAVE_API_KEY == "YOUR_BRAVE_API_KEY":
        console.log("[yellow]Warning: BRAVE_API_KEY not set. Skipping uniqueness verification.[/yellow]")
        return {
            "is_unique": True, # Assume unique for offline testing
            "search_query_used": f'"{text_to_check}"',
            "search_result_count": 0,
            "reason": "Skipped due to missing API key."
        }

    try:
        brave = Brave(BRAVE_API_KEY)
        # Use quotes for an exact match search
        query = f'"{text_to_check}"'
        search_results = brave.search(q=query, count=5) # Request a few results

        web_results = search_results.web_results or []
        result_count = len(web_results)

        # Check if the source URL is in the results
        source_in_results = any(source_url in result.url for result in web_results)

        # Uniqueness criteria: 1 or 2 results, and the source must be one of them.
        if result_count > 2:
            return {"is_unique": False, "search_result_count": result_count, "reason": "Too many results."}

        if result_count > 0 and not source_in_results:
             return {"is_unique": False, "search_result_count": result_count, "reason": "Results found, but none match the source URL."}

        return {
            "is_unique": True,
            "search_query_used": query,
            "search_result_count": result_count,
            "reason": "String appears to be unique to the source."
        }

    except Exception as e:
        console.log(f"[red]Error during Brave Search API call: {e}[/red]")
        return {"is_unique": False, "reason": f"API Error: {e}"}


# --- Generator Loading ---

def get_generators():
    """Dynamically imports all generator modules from the 'generators' directory."""
    generators = {}
    if not os.path.exists('generators'):
        return generators

    for (_, name, _) in pkgutil.iter_modules(['generators']):
        try:
            module = importlib.import_module(f'generators.{name}')
            if hasattr(module, 'DOMAIN_NAME') and hasattr(module, 'generate'):
                generators[module.DOMAIN_NAME] = module.generate
        except Exception as e:
            console.log(f"[red]Could not load generator '{name}': {e}[/red]")
    return generators

# --- Core Functions ---

def handle_generate(args):
    """Handles the 'generate' command."""
    console.log(f"[bold cyan]Starting benchmark generation...[/bold cyan]")
    os.makedirs(BENCHMARKS_DIR, exist_ok=True)

    all_generators = get_generators()
    target_generators = args.domains.split(',') if args.domains else all_generators.keys()

    if not all_generators:
        console.log("[bold red]No generator modules found in the 'generators' directory.[/bold red]")
        console.log("Please create a 'generators' directory with generator files (e.g., 'github.py').")
        return

    for domain in target_generators:
        if domain not in all_generators:
            console.log(f"[yellow]Warning: Generator for domain '{domain}' not found. Skipping.[/yellow]")
            continue

        console.log(f"\n[bold]Generating for domain: {domain}[/bold]")
        generator_func = all_generators[domain]

        try:
            qa_pairs = generator_func(args.count, console, verify_uniqueness)

            if not qa_pairs:
                console.log(f"[yellow]Generator for '{domain}' did not return any Q/A pairs.[/yellow]")
                continue

            # Write to file
            filepath = os.path.join(BENCHMARKS_DIR, f"{domain}_benchmark.json")
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(qa_pairs, f, indent=2, ensure_ascii=False)

            console.log(f"[green]Successfully generated {len(qa_pairs)} Q/A pairs for '{domain}'.[/green]")
            console.log(f"Saved to [bold]{filepath}[/bold]")

        except Exception as e:
            console.log(f"[bold red]An error occurred while running the '{domain}' generator: {e}[/bold red]")


def handle_evaluate(args):
    """Handles the 'evaluate' command."""
    console.log(f"[bold cyan]Starting evaluation for model: {args.model}[/bold cyan]")

    if not OPENAI_API_KEY or OPENAI_API_KEY == "YOUR_OPENAI_API_KEY":
        console.log("[bold red]Error: OPENAI_API_KEY is not set. Cannot run evaluation.[/bold red]")
        return

    client = openai.OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE)

    benchmark_files = args.benchmarks.split(',')
    results = []
    total_correct = 0
    total_evaluated = 0

    for file_path in benchmark_files:
        if not os.path.exists(file_path):
            console.log(f"[yellow]Warning: Benchmark file not found: {file_path}. Skipping.[/yellow]")
            continue

        with open(file_path, 'r', encoding='utf-8') as f:
            qa_pairs = json.load(f)

        domain = os.path.basename(file_path).replace('_benchmark.json', '')
        console.log(f"\n[bold]Evaluating domain: {domain}[/bold]")

        for i, qa in enumerate(qa_pairs):
            console.log(f"  - Evaluating item {i+1}/{len(qa_pairs)} ({qa['id']})...", end="")
            is_correct = False
            error_message = None
            llm_response_text = ""

            try:
                response = client.chat.completions.create(
                    model=args.model,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant. Answer the user's question directly and concisely."},
                        {"role": "user", "content": qa['question']}
                    ],
                    temperature=0.0,
                    max_tokens=150
                )
                llm_response_text = response.choices[0].message.content.strip()

                if qa['eval_method'] == 'string_match':
                    # Simple case-insensitive check
                    if qa['answer'].lower() in llm_response_text.lower():
                        is_correct = True
                else:
                    # Placeholder for llm-as-judge
                    is_correct = False # Not implemented yet
                    error_message = "llm-as-judge not implemented"

            except Exception as e:
                error_message = str(e)
                console.log(f"[red] API Error: {e}[/red]")

            results.append({
                "id": qa['id'],
                "domain": domain,
                "question": qa['question'],
                "expected_answer": qa['answer'],
                "llm_response": llm_response_text,
                "is_correct": is_correct,
                "error": error_message
            })

            if is_correct:
                total_correct += 1
                console.log("[green]Correct[/green]")
            else:
                console.log("[red]Incorrect[/red]")

            total_evaluated += 1

    # Print summary table
    console.log("\n\n[bold underline]Evaluation Summary[/bold underline]")
    table = Table(title=f"Model: {args.model}")
    table.add_column("Domain", justify="left", style="cyan")
    table.add_column("Correct", justify="right", style="green")
    table.add_column("Incorrect", justify="right", style="red")
    table.add_column("Total", justify="right")
    table.add_column("Accuracy", justify="right", style="bold magenta")

    domain_summary = {}
    for res in results:
        d = res['domain']
        if d not in domain_summary:
            domain_summary[d] = {"correct": 0, "total": 0}
        domain_summary[d]['total'] += 1
        if res['is_correct']:
            domain_summary[d]['correct'] += 1

    for domain, data in domain_summary.items():
        incorrect = data['total'] - data['correct']
        accuracy = (data['correct'] / data['total'] * 100) if data['total'] > 0 else 0
        table.add_row(
            domain,
            str(data['correct']),
            str(incorrect),
            str(data['total']),
            f"{accuracy:.2f}%"
        )

    total_incorrect = total_evaluated - total_correct
    total_accuracy = (total_correct / total_evaluated * 100) if total_evaluated > 0 else 0
    table.add_row("---", "---", "---", "---", "---")
    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{total_correct}[/bold]",
        f"[bold]{total_incorrect}[/bold]",
        f"[bold]{total_evaluated}[/bold]",
        f"[bold magenta]{total_accuracy:.2f}%[/bold magenta]"
    )

    console.print(table)


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(description="Reality Anchor Benchmark Tool for LLMs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- Generate Command ---
    gen_parser = subparsers.add_parser("generate", help="Generate benchmark Q/A pairs from various domains.")
    gen_parser.add_argument("--domains", type=str, help="Comma-separated list of domains to generate (e.g., 'github,reddit'). Defaults to all available generators.")
    gen_parser.add_argument("--count", type=int, default=10, help="Number of Q/A pairs to attempt to generate per domain.")
    gen_parser.set_defaults(func=handle_generate)

    # --- Evaluate Command ---
    eval_parser = subparsers.add_parser("evaluate", help="Evaluate an LLM against specified benchmark files.")
    eval_parser.add_argument("--model", type=str, required=True, help="The model identifier to evaluate (e.g., 'gpt-4o', 'anthropic/claude-3-opus').")
    eval_parser.add_argument("--benchmarks", type=str, required=True, help="Comma-separated list of benchmark JSON files to use for evaluation.")
    eval_parser.set_defaults(func=handle_evaluate)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
