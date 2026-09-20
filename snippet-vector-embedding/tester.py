from encoder_only_VE import verify_code_semantics
import re

if __name__ == "__main__": 
  txt = open("testing_snippets.txt", encoding="utf-8").read()
  parts = re.split(r"^#@@ (.+)$", txt, flags=re.M)
  labels, snippets = parts[1::2], [c.strip() for c in parts[2::2]]

  original, candidates = snippets[0], snippets[1:]
  cand_labels = labels[1:]

  score = verify_code_semantics(original,candidates)

  for label, s in zip(cand_labels, score):   # sin ordenar: así se ve la curva
      print(f"{s:.4f}  {label.split('|')[0].strip()}")