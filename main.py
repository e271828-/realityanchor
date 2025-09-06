# main.py
import argparse
import json
import os
import importlib
import pkgutil
import re
import time
from datetime import datetime
from rich.console import Console
from rich.table import Table
import requests
import openai
from brave import Brave


# --- Configuration ---
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "YOUR_BRAVE_API_KEY")
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")

BENCHMARKS_DIR = "benchmarks"
RUNS_DIR = "runs"
console = Console()

# --- Uniqueness Verification ---

def verify_uniqueness(text_to_check: str, source_url: str) -> dict:
    """Verifies the uniqueness of a string using the Brave Search API."""
    if not BRAVE_API_KEY or BRAVE_API_KEY == "YOUR_BRAVE_API_KEY":
        console.log("[yellow]Warning: BRAVE_API_KEY not set. Skipping uniqueness verification.[/yellow]")
        return {
            "is_unique": True, "search_query_used": f'"{text_to_check}"',
            "search_result_count": 0, "reason": "Skipped due to missing API key."
        }
    try:
        brave = Brave(BRAVE_API_KEY)
        query = f'"{text_to_check}"'
        search_results = brave.search(q=query, count=5)
        web_results = search_results.web_results or []
        result_count = len(web_results)
        source_in_results = any(source_url in result.url for result in web_results)
        if result_count > 2:
            return {"is_unique": False, "search_result_count": result_count, "reason": "Too many results."}
        if result_count > 0 and not source_in_results:
             return {"is_unique": False, "search_result_count": result_count, "reason": "Results found, but none match the source URL."}
        return {
            "is_unique": True, "search_query_used": query,
            "search_result_count": result_count, "reason": "String appears to be unique to the source."
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

# --- Helper functions for grading ---

_UNKNOWN_PATTERNS = re.compile(
    r"\b("
    r"unknown|i\s+don'?t\s+know|do\s+not\s+know|not\s+sure|unsure|"
    r"cannot\s+determine|can't\s+determine|no\s+idea|"
    r"insufficient\s+(info|information)|not\s+enough\s+information"
    r")\b",
    flags=re.IGNORECASE
)

def is_unknown_response(text: str) -> bool:
    """Heuristic match for abstentions/IDK."""
    if not text:
        return False
    return bool(_UNKNOWN_PATTERNS.search(text.strip()))

def classify_response(expected_answer: str, llm_text: str) -> str:
    """
    Returns one of: 'correct', 'unknown', 'incorrect'.
    - For Yes/No targets, expects yes/no/unknown.
    - For other targets, checks inclusion for simplicity, with 'unknown' detection.
    """
    if not llm_text:
        return "incorrect"

    text = llm_text.strip()
    ltext = text.lower().strip()

    if is_unknown_response(ltext):
        return "unknown"

    exp = (expected_answer or "").strip().lower()

    # Yes/No questions
    if exp in ["yes", "no"]:
        # Normalize to pure token if possible
        if re.fullmatch(r"\s*yes[.!]?\s*", ltext):
            pred = "yes"
        elif re.fullmatch(r"\s*no[.!]?\s*", ltext):
            pred = "no"
        else:
            # Fall back: if only one of yes/no appears, treat as that
            has_yes = "yes" in ltext
            has_no = "no" in ltext
            if has_yes and not has_no:
                pred = "yes"
            elif has_no and not has_yes:
                pred = "no"
            else:
                pred = None
        if pred is None:
            return "incorrect"
        return "correct" if pred == exp else "incorrect"

    # Non-Yes/No: simple containment match
    if exp and exp in ltext:
        return "correct"

    return "incorrect"

def score_for_classification(cls: str, correct_score: float, unknown_credit: float, wrong_penalty: float) -> float:
    """
    Map classification to a scalar score.
    correct -> +correct_score
    unknown -> +unknown_credit
    incorrect -> -wrong_penalty
    """
    if cls == "correct":
        return correct_score
    if cls == "unknown":
        return unknown_credit
    return -wrong_penalty

# --- Core Functions ---

def handle_generate(args):
    """Handles the 'generate' command."""
    console.log(f"[bold cyan]Starting benchmark generation...[/bold cyan]")
    os.makedirs(BENCHMARKS_DIR, exist_ok=True)

    all_generators = get_generators()
    target_generators = args.domains.split(',') if args.domains else all_generators.keys()

    if not all_generators:
        console.log("[bold red]No generator modules found in the 'generators' directory.[/bold red]")
        return

    for domain in target_generators:
        console.log(f"\n[bold]Processing domain: {domain}[/bold]")

        filepath = os.path.join(BENCHMARKS_DIR, f"{domain}_benchmark.json")
        if os.path.exists(filepath) and not args.force:
            console.log(f"Benchmark file for '{domain}' already exists. [yellow]Skipping.[/yellow]")
            console.log("Use the --force flag to regenerate.")
            continue

        generator_func = all_generators[domain]

        try:
            qa_pairs = generator_func(args.count, console, verify_uniqueness)
            if not qa_pairs:
                console.log(f"[yellow]Generator for '{domain}' did not return any Q/A pairs.[/yellow]")
                continue

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(qa_pairs, f, indent=2, ensure_ascii=False)

            console.log(f"[green]Successfully generated {len(qa_pairs)} Q/A pairs for '{domain}'.[/green]")
            console.log(f"Saved to [bold]{filepath}[/bold]")

        except Exception as e:
            console.log(f"[bold red]An error occurred while running the '{domain}' generator: {e}[/bold red]")

def print_summary_table(all_results, model_name):
    """Prints a summary table of results to the console."""
    console.log("\n\n[bold underline]Evaluation Summary[/bold underline]")
    table = Table(title=f"Model: {model_name}")
    table.add_column("Domain", justify="left", style="cyan")
    table.add_column("Correct", justify="right", style="green")
    table.add_column("Unknown", justify="right", style="yellow")
    table.add_column("Incorrect", justify="right", style="red")
    table.add_column("Total", justify="right")
    table.add_column("Accuracy", justify="right", style="bold magenta")
    table.add_column("AvgScore", justify="right", style="magenta")

    domain_summary = {}
    for res in all_results:
        d = res['domain']
        if d not in domain_summary:
            domain_summary[d] = {"correct": 0, "unknown": 0, "incorrect": 0, "total": 0, "score_sum": 0.0}
        domain_summary[d]['total'] += 1

        cls = res.get('classification')
        if not cls:
            # Back-compat with older runs lacking tri-state classification
            cls = "correct" if res.get('is_correct') else "incorrect"
        if cls not in ["correct", "unknown", "incorrect"]:
            cls = "incorrect"

        domain_summary[d][cls] += 1
        domain_summary[d]['score_sum'] += float(res.get('score', 1.0 if cls == "correct" else 0.0))

    total_correct = sum(d['correct'] for d in domain_summary.values())
    total_unknown = sum(d['unknown'] for d in domain_summary.values())
    total_evaluated = sum(d['total'] for d in domain_summary.values())
    total_incorrect = total_evaluated - total_correct - total_unknown
    total_score = sum(d['score_sum'] for d in domain_summary.values())

    for domain, data in sorted(domain_summary.items()):
        accuracy = (data['correct'] / data['total'] * 100) if data['total'] > 0 else 0
        avg_score = (data['score_sum'] / data['total']) if data['total'] > 0 else 0.0
        table.add_row(
            domain,
            str(data['correct']),
            str(data['unknown']),
            str(data['total'] - data['correct'] - data['unknown']),
            str(data['total']),
            f"{accuracy:.2f}%",
            f"{avg_score:.3f}"
        )

    total_accuracy = (total_correct / total_evaluated * 100) if total_evaluated > 0 else 0
    total_avg_score = (total_score / total_evaluated) if total_evaluated > 0 else 0.0
    table.add_row("---", "---", "---", "---", "---", "---", "---")
    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{total_correct}[/bold]",
        f"[bold]{total_unknown}[/bold]",
        f"[bold]{total_incorrect}[/bold]",
        f"[bold]{total_evaluated}[/bold]",
        f"[bold magenta]{total_accuracy:.2f}%[/bold magenta]",
        f"[bold magenta]{total_avg_score:.3f}[/bold magenta]"
    )
    console.print(table)


def handle_evaluate(args):
    """Handles the 'evaluate' command, running the LLM and saving structured results."""
    console.log(f"[bold cyan]Starting evaluation for model: {args.model}[/bold cyan]")

    if not OPENAI_API_KEY or OPENAI_API_KEY == "YOUR_OPENAI_API_KEY":
        console.log("[bold red]Error: OPENAI_API_KEY is not set. Cannot run evaluation.[/bold red]")
        return

    client = openai.OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE)

    # --- Create structured directory for this run ---
    run_timestamp = int(time.time())
    # Sanitize model name for directory path
    sane_model_name = re.sub(r'[^a-zA-Z0-9_-]', '_', args.model)
    run_dir = os.path.join(RUNS_DIR, sane_model_name, str(run_timestamp))
    os.makedirs(run_dir, exist_ok=True)
    console.log(f"Saving results to: [bold]{run_dir}[/bold]")

    # inspired by Kalai et al. (2025), "Why Language Models Hallucinate":
    # binary 0/1 grading rewards guessing. we use non-binary scoring that
    # rewards abstention ("Unknown") and penalizes wrong answers
    # to reduce hallucination incentives.
    correct_score = 1.0
    unknown_credit = float(args.unknown_credit)
    wrong_penalty = float(args.wrong_penalty)

    # Optional "confidence-target" scoring: wrong_penalty = t/(1-t)
    # (See paper’s suggestion to set an explicit threshold t.)
    risk_t = args.risk_threshold
    risk_penalty = None
    if risk_t is not None:
        if not (0.0 <= risk_t < 1.0):
            console.log("[red]--risk-threshold must be in [0.0, 1.0). Ignoring.[/red]")
        else:
            risk_penalty = risk_t / (1.0 - risk_t)
            wrong_penalty = risk_penalty  # override unless user re-overrides via flag

    # Write run metadata
    meta = {
        "model": args.model,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "benchmarks": args.benchmarks.split(','),
        "scoring": {
            "correct_score": correct_score,
            "unknown_credit": unknown_credit,
            "wrong_penalty": wrong_penalty,
            "risk_threshold": risk_t,
            "risk_penalty_applied": risk_penalty,
        },
    }
    with open(os.path.join(run_dir, "meta.json"), "w", encoding="utf-8") as fmeta:
        json.dump(meta, fmeta, indent=2)

    # Build dynamic system prompt to make the model aware of scoring
    scoring_line = (
        f"Scoring: Correct = +{correct_score}, Unknown = +{unknown_credit}, Incorrect = -{wrong_penalty}. "
        f"If you are not sufficiently confident, prefer answering 'Unknown' rather than guessing."
    )
    yesno_line = "For Yes/No questions, respond with exactly 'Yes', 'No', or 'Unknown'."
    base_system = (
        "You are a helpful assistant. Answer the user's question directly and concisely. "
        + yesno_line + " " + scoring_line
    )

    benchmark_files = args.benchmarks.split(',')
    all_results = []

    for file_path in benchmark_files:
        if not os.path.exists(file_path):
            console.log(f"[yellow]Warning: Benchmark file not found: {file_path}. Skipping.[/yellow]")
            continue

        with open(file_path, 'r', encoding='utf-8') as f:
            qa_pairs = json.load(f)

        domain = os.path.basename(file_path).replace('_benchmark.json', '')
        console.log(f"\n[bold]Evaluating domain: {domain}[/bold]")

        domain_results = []
        for i, qa in enumerate(qa_pairs):
            console.log(f"  - Evaluating item {i+1}/{len(qa_pairs)} ({qa['id']})...", end="")
            error_message = None
            llm_response_text = ""
            classification = "incorrect"
            is_correct = False

            try:
                response = client.chat.completions.create(
                    model=args.model,
                    messages=[
                        {"role": "system", "content": base_system},
                        {"role": "user", "content": qa['question']}
                    ],
                    temperature=0.0, max_tokens=150
                )
                llm_response_text = response.choices[0].message.content.strip()
                expected_answer = qa['answer']

                classification = classify_response(expected_answer, llm_response_text)
                is_correct = classification == "correct"

            except Exception as e:
                error_message = str(e)
                console.log(f"[red] API Error: {e}[/red]")

            # Compute score under the configured scheme
            score = score_for_classification(
                classification, correct_score=correct_score,
                unknown_credit=unknown_credit, wrong_penalty=wrong_penalty
            )

            result_item = {
                "id": qa['id'], "domain": domain, "question": qa['question'],
                "expected_answer": qa['answer'], "llm_response": llm_response_text,
                "classification": classification,  # 'correct' | 'unknown' | 'incorrect'
                "is_correct": is_correct,          # kept for back-compat
                "score": score,
                "error": error_message
            }
            domain_results.append(result_item)
            all_results.append(result_item)

            if classification == "correct":
                console.log("[green]Correct[/green]")
            elif classification == "unknown":
                console.log("[yellow]Unknown[/yellow]")
            else:
                console.log("[red]Incorrect[/red]")

        # --- Save results for this domain ---
        domain_run_dir = os.path.join(run_dir, domain)
        os.makedirs(domain_run_dir, exist_ok=True)
        with open(os.path.join(domain_run_dir, "answers.json"), 'w', encoding='utf-8') as f:
            json.dump(domain_results, f, indent=2, ensure_ascii=False)

    print_summary_table(all_results, args.model)

def handle_report(args):
    """Handles the 'report' command, generating stats from saved JSON files."""
    run_dir = args.run_dir
    if not os.path.isdir(run_dir):
        console.log(f"[red]Error: Run directory not found at '{run_dir}'[/red]")
        return

    console.log(f"Generating report from run directory: [bold]{run_dir}[/bold]")

    all_results = []
    # Extract model name from directory path for the report title
    model_name = os.path.basename(os.path.dirname(run_dir))

    for root, _, files in os.walk(run_dir):
        for file in files:
            if file == "answers.json":
                try:
                    with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                        all_results.extend(json.load(f))
                except json.JSONDecodeError:
                    console.log(f"[yellow]Warning: Could not parse JSON file at '{os.path.join(root, file)}'[/yellow]")

    if not all_results:
        console.log("[red]No valid 'answers.json' files found in the specified directory.[/red]")
        return

    print_summary_table(all_results, model_name)


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(description="Reality Anchor Benchmark Tool for LLMs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- Generate Command ---
    gen_parser = subparsers.add_parser("generate", help="Generate benchmark Q/A pairs from various domains.")
    gen_parser.add_argument("--domains", type=str, help="Comma-separated list of domains to generate (e.g., 'github,reddit'). Defaults to all available generators.")
    gen_parser.add_argument("--count", type=int, default=10, help="Number of Q/A pairs to attempt to generate per domain.")
    gen_parser.add_argument("--force", action="store_true", help="Force regeneration of benchmark files even if they exist.")
    gen_parser.set_defaults(func=handle_generate)

    # --- Evaluate Command ---
    eval_parser = subparsers.add_parser("evaluate", help="Evaluate an LLM and save results.")
    eval_parser.add_argument("--model", type=str, required=True, help="The model identifier to evaluate (e.g., 'gpt-4o').")
    eval_parser.add_argument("--benchmarks", type=str, required=True, help="Comma-separated list of benchmark JSON files to use for evaluation.")

    # New scoring options:
    eval_parser.add_argument("--unknown-credit", type=float, default=0.25,
                             help="Partial credit for abstaining with 'Unknown' (default: 0.25).")
    eval_parser.add_argument("--wrong-penalty", type=float, default=1.0,
                             help="Penalty magnitude for incorrect answers; applied as negative score (default: 1.0).")
    eval_parser.add_argument("--risk-threshold", type=float, default=None,
                             help="Optional confidence target t in [0,1). If set, wrong penalty is auto-set to t/(1-t).")

    eval_parser.set_defaults(func=handle_evaluate)

    # --- Report Command ---
    report_parser = subparsers.add_parser("report", help="Generate summary stats from a previous evaluation run.")
    report_parser.add_argument("--run-dir", type=str, required=True, help="Path to the specific run directory (e.g., 'runs/local-model/1678886400').")
    report_parser.set_defaults(func=handle_report)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()