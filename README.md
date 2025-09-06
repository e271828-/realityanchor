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

### Brief note on "Why Language Models Hallucinate" (Kalai et al 2025) and how we apply it

The paper argues that binary 0-1 grading rewards guessing and thus perpetuates hallucinations. Models that always guess outperform models that honestly abstain under standard accuracy. The fix they recommend is that benchmarks should score by giving credit for uncertainty and penalizing wrong answers, optionally with an explicit confidence target t that implies a penalty of t/(1−t) for incorrect responses.

Reality Anchor adopts this principle in the evaluation harness:

- Evals are tri-state: correct, unknown/IDK, incorrect.
- Scoring gives partial credit for Unknown and applies a penalty for incorrect answers.
- Optionally, you can set a "confidence target" t. The harness then uses the paper's penalty t/(1−t), making abstention optimal below that confidence.

This aligns the benchmark with truthful behavior and reduces incentives to bluff.


## Methodology

The benchmark uses a simple idea: find facts that are hard to guess and easy to verify.

It consists of two main components:

1. Generators: modules that locate obscure information. Each generator targets a specific domain and employs heuristics to find verifiable facts unlikely to be present in a generalized dataset.

2. Eval harness: uses the generated data to create question-answer pairs. It then queries one or more LLMs via an API and evaluates their responses against ground truth.

The current generators create questions that are verifiable via simple string matching to minimize ambiguity and the need for unstable 'llm-as-judge' evals.

### Hallucination-aware scoring

The system prompt tells models to prefer "Unknown" when not confident, and for yes/no tasks to answer exactly "Yes", "No", or "Unknown".

Responses are classified as:

  - correct: matches expected answer (for yes/no or string-inclusion cases),
  - unknown: contains abstention phrases (e.g. "Unknown", "I don't know", "Not sure", etc.),
  - incorrect: otherwise.

Each item receives a scalar score:

  - correct = +1.0
  - unknown = +unknown_credit (default 0.25)
  - incorrect = −wrong_penalty (default 1.0)

Confidence-target mode: set --risk-threshold t in [0,1). The harness applies wrong_penalty = t/(1−t), mirroring the paper's suggested scheme where abstaining is optimal unless the model's confidence exceeds t.

The overall report includes both traditional accuracy and the Kalai-style average score, so you can see how models trade off guessing vs. truthfulness.


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
 - Support for any OpenAI-compatible API endpoint (e.g. LM Studio, Ollama).
 - Automatic, structured logging of all evaluation runs for reproducibility (`runs/<model_name>/<timestamp>/...`).
 - hallucination-aware scoring that partially credits abstentions and penalizes wrong answers.
 - optional confidence-target mode (--risk-threshold t) that uses penalty t/(1−t).
 - tri-state classification (correct/unknown/incorrect) per item, saved to answers.json.
 - summary table columns for Unknown count and AvgScore; per-run meta.json records scoring parameters.
 - Backwards compatible: is_correct is still logged for downstream tools that expect it.

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