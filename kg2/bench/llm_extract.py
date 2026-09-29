"""Second relation extractor for the V2 gold set: an LLM (Ollama) labels the same 400 blind items
the human annotators see, with the same instructions. Scored later against the humans, side by
side with PubTator3. The LLM never sees the answer key or PubTator3's label.

    python3 llm_extract.py --items items.tsv --out preds.jsonl --model qwen2.5:72b-instruct-q4_K_M
Resumable: items already in --out are skipped. Deterministic: temperature 0, fixed seed.
Server: $OLLAMA_HOST (default http://127.0.0.1:11434).
"""
import argparse
import csv
import json
import os
import time
import urllib.request

LABELS = ["positive_correlation", "negative_correlation", "association", "binding",
          "no_relation", "cannot_tell"]
PROMPT = """You are annotating biomedical sentences for relation extraction.

Sentence: "{sentence}"
Entity A: {a}
Entity B: {b}

Does the SENTENCE ITSELF state a relation between entity A and entity B? Choose exactly one:
- positive_correlation: both go up together, or A increases/activates B (or B increases A)
- negative_correlation: A decreases/inhibits B, or they change in opposite directions
- association: the sentence links A and B but gives no direction
- binding: A and B physically bind
- no_relation: both are mentioned but the sentence does not relate them
- cannot_tell: the sentence is too ambiguous to decide

Answer with JSON only: {{"relation": "<one label>"}}"""


def ask(host, model, prompt, threads, timeout):
    body = json.dumps({"model": model, "prompt": prompt, "stream": False, "format": "json",
                       "options": {"temperature": 0, "seed": 0, "num_thread": threads,
                                   "num_predict": 32}}).encode()
    req = urllib.request.Request(f"{host}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--shard", type=int, default=0, help="this shard (0-based)")
    ap.add_argument("--nshards", type=int, default=1, help="split items round-robin over N shards")
    a = ap.parse_args()
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    threads = int(os.environ.get("SLURM_CPUS_PER_TASK", "4"))
    items = list(csv.DictReader(open(a.items), delimiter="\t"))
    items = [it for i, it in enumerate(items) if i % a.nshards == a.shard]
    if a.limit:
        items = items[:a.limit]
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(l)["item"] for l in open(a.out) if l.strip()}
    todo = [it for it in items if it["item"] not in done]
    print(f"model {a.model}; items {len(items)}; already done {len(done)}; to do {len(todo)}", flush=True)
    with open(a.out, "a") as f:
        for n, it in enumerate(todo, 1):
            t0 = time.time()
            label, raw, err = "", "", ""
            for attempt in range(3):
                try:
                    r = ask(host, a.model, PROMPT.format(sentence=it["sentence"], a=it["entity_a"],
                                                         b=it["entity_b"]), threads, 1800)
                    raw = r.get("response", "")
                    label = json.loads(raw).get("relation", "")
                    err = "" if label in LABELS else f"invalid label: {label!r}"
                    break
                except Exception as e:  # noqa: BLE001 — record, retry, never silently drop
                    err = f"{type(e).__name__}: {e}"
                    time.sleep(5)
            f.write(json.dumps({"item": it["item"], "model": a.model, "relation": label if not err else "",
                                "raw": raw, "error": err, "seconds": round(time.time() - t0, 1)}) + "\n")
            f.flush()
            if n % 25 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)} last {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
