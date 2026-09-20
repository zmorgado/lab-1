import sys

COMMON = ["the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "that", "for", "on", "with"]


def load(filename):
    f = open(filename, "r", encoding="utf-8")
    data = f.read()
    f.close()
    return data


def clean(raw):
    """Replace punctuation with spaces and split into lowercase words."""
    result = []
    for line in raw.lower().split("\n"):
        buffer = ""
        for ch in line:
            if ch.isalpha() or ch == "'":
                buffer += ch
            else:
                buffer += " "
        for piece in buffer.split():
            result.append(piece)
    return result


def frequencies(tokens):
    table = {}
    total = 0
    for tok in tokens:
        if tok in COMMON or len(tok) < 2:
            continue
        if tok in table:
            table[tok] += 1
        else:
            table[tok] = 1
        total += 1
    return table, total


def best(table, k):
    """Selection sort of the k largest entries (count desc, then word asc)."""
    items = list(table.items())
    chosen = []
    while items and len(chosen) < k:
        top = items[0]
        for entry in items:
            if entry[1] > top[1] or (entry[1] == top[1] and entry[0] < top[0]):
                top = entry
        chosen.append(top)
        items.remove(top)
    return chosen


def show(chosen, total):
    print("word".ljust(15) + "count".rjust(6) + "share".rjust(8))
    for word, count in chosen:
        pct = (count * 100.0 / total) if total > 0 else 0.0
        print(word.ljust(15) + str(count).rjust(6) + ("%.1f%%" % pct).rjust(8))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python word_freq_B.py FILE [TOP]")
        sys.exit(1)
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    table, total = frequencies(clean(load(sys.argv[1])))
    show(best(table, k), total)
