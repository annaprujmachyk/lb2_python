"""Reproducible local corpus, no network needed.

Usage: python scripts/make_benchmark_corpus.py --documents 300 --repeat 200
"""
from pathlib import Path
import argparse

WORDS = 'Python concurrency threading processes global interpreter lock inverted index tokenization performance benchmark search engine unicode document '.split()

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--documents',type=int,default=300)
    p.add_argument('--repeat',type=int,default=200)
    p.add_argument('--out',type=Path,default=Path('data/benchmark'))
    a = p.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    for i in range(a.documents):
        text = ' '.join(WORDS[(j+i)%len(WORDS)] for j in range(a.repeat))
        (a.out / f'doc_{i:05}.txt').write_text(text,encoding='utf-8')
    print(f'Created {a.documents} documents in {a.out}')

if __name__ == '__main__': main()
