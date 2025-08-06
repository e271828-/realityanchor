# Reality Anchor

An inference-time LLM dataset probe framework.

Find out what's really being used to train your favorite closed models.


## Motivation

Reality Anchor is a benchmarking framework designed to probe the nature of LLM training data.

Its goal is to indicate whether LLM pretraining data includes the raw web, or has been heavily preprocessed or even limited to synthetic datasets.

Models trained exclusively on synthetic or heavily sanitized data may excel at some tasks but are hypothesized to lack "reality anchors"; specific, obscure, and non-deducible facts tied to a particular time and source. This benchmark aims to create a verifiable test for knowledge of these anchors.

In principle, this provides a means to:

- Rank models by real world knowledge: This kind of dynamic benchmark is hard to cheat. If relative scores on Reality Anchor diverge from benchmarks, it would not be surprising if that strongly correlates to models being better or worse at understanding real world user queries.

- Analyze knowledge cutoffs: By generating data from specific time periods, one can probe the temporal boundaries of a model's knowledge and figure out training sample depth; is it well-distributed, or concentrated on more recent documents?

- Compare model grounding: Evaluate how different models perform on retrieval of obscure, real-world information.

- Investigate training data composition: The presence or absence of these anchors can provide clues about the diversity and nature of a model's pre-training corpus.


## Methodology

The benchmark operates on a simple but powerful principle: find facts that are hard to guess and easy to verify.

It consists of two main components:

1. Generators: modules that scour locate obscure information. Each generator targets a specific domain and employs heuristics to find verifiable "facts" that are unlikely to be present in a generalized dataset.

2. Eval harness: uses the generated data to create question-answer pairs. It then queries one or more LLMs via an API and evaluates their responses against ground truth.

The current generators create questions that are verifiable via simple string matching to minimize ambiguity and the need for unstable 'llm-as-judge' evals.

---

## Current state

The project is functional and includes the following components:

Generators:
 - `github`: Finds obscure variable assignments in low-starred, older repositories.
 - `github_popular`: Finds obscure variable assignments in high-starred, popular repositories.
 - `reddit`: Finds uncommon keywords in comments from niche subreddits.
 - `pypi`: Finds specific, non-trivial package requirements from old PyPI packages.
 - `wikipedia`: Finds uncommon keywords in the first sentence of articles from niche categories.

Eval + reporting:
 - A CLI for generating benchmarks, evaluating models, and re-generating reports from past runs.
 - Support for any OpenAI-compatible API endpoint (e.g., LM Studio, Ollama).
 - Automatic, structured logging of all evaluation runs for reproducibility (`runs/<model_name>/<timestamp>/...`).

---

## How to use

### Setup

Install dependencies:

    pip install -r requirements.txt

### Config

API Keys (optional but recommended):

For full functionality (especially uniqueness verification), set the following environment variables:

    export BRAVE_API_KEY="your_brave_search_api_key"
    export GITHUB_API_TOKEN="your_github_personal_access_token"

but neither is required to run; it'll just skip uniqueness tests. Github will work either way.

Make sure you set your OAI-compat env var, e.g. for LM Studio, in run_eval.sh or via env var if running evals directly:

    export OPENAI_API_BASE="http://localhost:1234/v1"
    export OPENAI_API_KEY="not-needed"

Models to test:

To evaluate multiple models in a single run, create a `models.txt` file and list one model identifier per line:

    ```bash
    cat > models.txt <<EOF
    qwen3-30b-a3b-instruct-2507-mlx
    xbai-o4
    EOF
    ```

### Running the benchmark

The primary way to run the benchmark is with the provided bash script. Ensure your local LLM server (e.g., LM Studio) is running.

Run evaluation for all models in `models.txt`:

    ./run_eval.sh

Run evaluation for a single, specific model:

    ./run_eval.sh "specific-model-name"

By default, the script will not regenerate benchmark files that already exist. Use the `--force` or `-f` flag to override this.

Force regeneration of all benchmark data:

    ./run_eval.sh --force

### Generating reports from past runs

You can regenerate the summary table from any previous run without re-running the expensive API calls.

1.  Find the run directory you want to report on inside the `runs/` folder.
2.  Run the `report` command:

    python main.py report --run-dir "runs/Llama-3-8B-Instruct-GGUF/1722981600"

---

## Limitations

The main limitation is in using yes/no questions at all. This has very low cardinality, so models will guess and thus some % will always be correct.

The rare string questions as in github are much more robust, and should have a 0% FP rate.

---

## Future work

- Add new generators for data sources with time-stamped, obscure facts: arXiv, Stack Overflow, public mailing lists, historical Usenet archives.

- Temporal filtering: Add a `--year` flag to the `generate` and `evaluate` commands to explicitly test knowledge cutoffs.

- Efficiency: current benchmark can run and build itself pretty fast, but some generators can be optimized further.
