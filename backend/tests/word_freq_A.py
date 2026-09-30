import argparse
import re
from collections import Counter

STOPWORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "that", "for", "on", "with"}


def read_text(path):
    """Read a UTF-8 text file and return its content as a string."""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def tokenize(text):
    """Lowercase the text and extract alphabetic words."""
    return re.findall(r"[a-z']+", text.lower())


def remove_stopwords(words, stopwords=STOPWORDS):
    """Drop very common words that carry little meaning."""
    return [word for word in words if word not in stopwords and len(word) > 1]


def count_words(words):
    """Return a Counter mapping each word to its number of occurrences."""
    return Counter(words)


def top_words(counter, limit=10):
    """Return the `limit` most common words, ties broken alphabetically."""
    ranked = sorted(counter.items(), key=lambda pair: (-pair[1], pair[0]))
    return ranked[:limit]


def format_report(pairs, total):
    """Build a printable table with counts and percentages."""
    lines = [f"{'word':<15}{'count':>6}{'share':>8}"]
    for word, count in pairs:
        share = 100 * count / total if total else 0.0
        lines.append(f"{word:<15}{count:>6}{share:>7.1f}%")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Word frequency report")
    parser.add_argument("path", help="text file to analyse")
    parser.add_argument("-n", "--top", type=int, default=10)
    args = parser.parse_args()

    words = remove_stopwords(tokenize(read_text(args.path)))
    counter = count_words(words)
    print(format_report(top_words(counter, args.top), len(words)))


if __name__ == "__main__":
    main()
