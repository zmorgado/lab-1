import torch
from unixcoder import UniXcoder


def verify_code_semantics(query: str, code_snippets: list, model=None) -> list:
    """
    Computes cosine similarity scores between a natural language query
    and a list of code snippets using UniXcoder in <encoder-only> mode.

    Parameters:
        query       : The reference code snippet (string).
        code_snippets: List of candidate code snippets to compare against.
        model       : Optional pre-loaded UniXcoder instance. If None,
                      a new model is loaded internally.
    """
    # 1. Select hardware device (GPU if available, else CPU)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # 2. Load model if not provided
    if model is None:
        model = UniXcoder("microsoft/unixcoder-base").to(device)
        model.eval()

    # 3. Tokenize query and code snippets in <encoder-only> mode
    query_tokens = model.tokenize([query], max_length=512, mode="<encoder-only>", padding=True)
    code_tokens = model.tokenize(code_snippets, max_length=512, mode="<encoder-only>", padding=True)

    query_ids = torch.tensor(query_tokens).to(device)
    code_ids = torch.tensor(code_tokens).to(device)

    # 4. Extract 768-dimensional mean-pooled sequence vectors
    with torch.no_grad():
        _, query_emb = model(query_ids)
        _, code_embs = model(code_ids)

    # 5. Apply L2 normalization
    norm_query = torch.nn.functional.normalize(query_emb, p=2, dim=1)
    norm_code = torch.nn.functional.normalize(code_embs, p=2, dim=1)

    # 6. Compute Cosine Similarity Matrix (handles single or multiple candidates)
    similarity_matrix = torch.mm(norm_query, norm_code.T)

    # Convert to a flat list of float scores
    scores = similarity_matrix.squeeze(0).tolist()
    return scores if isinstance(scores, list) else [scores]


if __name__ == "__main__":
    # Query string representing conceptual intent
    query = "sort dict by value"

    # Candidate code snippets (raw code text)
    candidate_snippets = [
        "def sort_dictionary(d):\n    return dict(sorted(d.items(), key=lambda item: item[1]))",
        "def compute_average(lst):\n    return sum(lst) / len(lst)"
    ]

    # Run semantic verification
    scores = verify_code_semantics(query, candidate_snippets)

    # Output results
    print(f"Query: '{query}'\n" + "-" * 45)
    for idx, (snippet, score) in enumerate(zip(candidate_snippets, scores), 1):
        first_line = snippet.split('\n')[0]
        print(f"Candidate {idx} [{first_line}]:\n  Similarity Score = {score:.4f}\n")

#cosine similarity scores for short natural language queries against code snippets typically range around 0.45 – 0.60for positive matches, while completely unrelated code (like `compute_average`) stays down near 0.10 – 0.15.
