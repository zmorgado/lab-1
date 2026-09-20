"""
tester.py — Semantic Similarity Comparator
------------------------------------------
Compares two code snippets using UniXcoder in encoder-only mode
with a 500-token limit. Prints the similarity score and a
resource/time report.

Usage:
    python tester.py <script1.py> <script2.py>

Example:
    python tester.py original.py modified.py
"""

import sys
import time
import tracemalloc
import os

import psutil
import torch
from encoder_only_VE import verify_code_semantics
from unixcoder import UniXcoder


def read_script(path: str) -> str:
    """Read a file and return its contents as a string."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def truncate_to_tokens(text: str, tokenizer, max_tokens: int = 500) -> str:
    """Truncate text to max_tokens if it exceeds that limit."""
    tokens = tokenizer.tokenize(text)
    if len(tokens) > max_tokens:
        token_ids = tokenizer.convert_tokens_to_ids(tokens[:max_tokens])
        return tokenizer.decode(token_ids, clean_up_tokenization_spaces=False)
    return text


def measure_resources(func, *args, **kwargs):
    """
    Execute func while tracking wall-clock time, CPU time,
    and memory consumption. Returns (result, metrics_dict).
    """
    process = psutil.Process(os.getpid())

    tracemalloc.start()
    start_wall = time.perf_counter()
    start_cpu_user = time.process_time()
    start_cpu_sys = time.thread_time()
    rss_before = process.memory_info().rss

    result = func(*args, **kwargs)

    end_wall = time.perf_counter()
    end_cpu_user = time.process_time()
    end_cpu_sys = time.thread_time()
    rss_after = process.memory_info().rss
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    try:
        page_faults = process.memory_full_info().pfaults
    except AttributeError:
        page_faults = None

    metrics = {
        "wall_time": end_wall - start_wall,
        "cpu_user": end_cpu_user - start_cpu_user,
        "cpu_sys": end_cpu_sys - start_cpu_sys,
        "cpu_total": (end_cpu_user - start_cpu_user) + (end_cpu_sys - start_cpu_sys),
        "rss_before_mb": rss_before / (1024 * 1024),
        "rss_after_mb": rss_after / (1024 * 1024),
        "rss_growth_mb": (rss_after - rss_before) / (1024 * 1024),
        "peak_alloc_kb": peak_mem / 1024,
        "current_alloc_kb": current_mem / 1024,
        "page_faults": page_faults,
        "cpu_cores": psutil.cpu_count(),
        "cpu_utilization": process.cpu_percent(interval=0),
        "num_threads": process.num_threads(),
        "open_fds": process.num_fds(),
    }
    return result, metrics


def print_report(scores, script1: str, script2: str, metrics: dict):
    """Print a formatted similarity score and resource report."""
    score = scores[0]

    # Determine verdict
    if score > 0.7:
        verdict = "Highly similar"
    elif score > 0.4:
        verdict = "Moderately similar"
    elif score > 0.1:
        verdict = "Slightly similar"
    elif score > -0.1:
        verdict = "Nearly unrelated"
    else:
        verdict = "Completely unrelated"

    print("\n" + "=" * 60)
    print("  SEMANTIC SIMILARITY REPORT")
    print("=" * 60)

    print(f"\n  Script 1 : {os.path.basename(script1)}")
    print(f"  Script 2 : {os.path.basename(script2)}")
    print(f"  Token limit: 500 tokens")
    print(f"\n  Cosine Similarity : {score:.4f}")
    print(f"  Verdict           : {verdict}")

    print(f"\n  --- Execution Time ---")
    print(f"  Wall-clock time   : {metrics['wall_time']:.4f} s")
    print(f"  CPU user time     : {metrics['cpu_user']:.4f} s")
    print(f"  CPU system time   : {metrics['cpu_sys']:.4f} s")
    print(f"  CPU total time    : {metrics['cpu_total']:.4f} s")
    print(f"  CPU cores         : {metrics['cpu_cores']}")
    print(f"  CPU utilization   : {metrics['cpu_utilization']:.1f}%")

    print(f"\n  --- Memory Usage ---")
    print(f"  RSS (before model): {metrics['rss_before_mb']:.2f} MB")
    print(f"  RSS (after model) : {metrics['rss_after_mb']:.2f} MB")
    print(f"  Memory growth     : {metrics['rss_growth_mb']:.2f} MB")
    print(f"  Peak allocation   : {metrics['peak_alloc_kb']:.1f} KB")
    print(f"  Current allocation: {metrics['current_alloc_kb']:.1f} KB")

    print(f"\n  --- System Resources ---")
    print(f"  Threads           : {metrics['num_threads']}")
    print(f"  Open file descriptors: {metrics['open_fds']}")
    if metrics["page_faults"] is not None:
        print(f"  Page faults (minor): {metrics['page_faults']}")

    print("\n" + "=" * 60)
    print("  END OF REPORT")
    print("=" * 60 + "\n")


def main():
    if len(sys.argv) != 3:
        print("Usage: python tester.py <script1.py> <script2.py>")
        print("Example: python tester.py original.py modified.py")
        sys.exit(1)

    script1_path = sys.argv[1]
    script2_path = sys.argv[2]

    # Validate files exist
    for path in [script1_path, script2_path]:
        if not os.path.isfile(path):
            print(f"Error: File not found: {path}")
            sys.exit(1)

    # Read scripts
    script1 = read_script(script1_path)
    script2 = read_script(script2_path)

    # Load model once (shared for tokenization and inference)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = UniXcoder("microsoft/unixcoder-base").to(device)
    model.eval()

    # Truncate to 500 tokens if needed
    script1_truncated = truncate_to_tokens(script1, model.tokenizer, 500)
    script2_truncated = truncate_to_tokens(script2, model.tokenizer, 500)

    orig_tokens = len(model.tokenizer.tokenize(script1))
    mod_tokens = len(model.tokenizer.tokenize(script2))

    # Measure similarity + resources
    def run_inference():
        return verify_code_semantics(
            script1_truncated, [script2_truncated], model=model
        )

    scores, metrics = measure_resources(run_inference)

    # Print report
    print_report(scores, script1_path, script2_path, metrics)
    print(f"  Token counts — Original: {orig_tokens} | Modified: {mod_tokens}")
    print()


if __name__ == "__main__":
    main()
