"""Repeatable Lab05 benchmarking and speedup chart.

Usage: python scripts/benchmark_lab05.py data/benchmark --repeats 3 --workers 1 2 4 8
Add --include-all-cpus for os.cpu_count() as requested in the methodology.
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import platform
import resource
import statistics
import sys
import threading
import time
from pathlib import Path

# Use editable installation or PYTHONPATH=src.
from findex.parallel import build_parallel_index


def rss_bytes() -> int:
    try:
        import psutil
        return psutil.Process().memory_info().rss
    except ImportError:
        # ru_maxrss is a high-water mark for process lifetime, not per-run.
        size = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(size * (1 if sys.platform == 'darwin' else 1024))


def child_cpu() -> float:
    r = resource.getrusage(resource.RUSAGE_CHILDREN)
    return r.ru_utime + r.ru_stime


def benchmark(root: Path, engines: list[str], counts: list[int], repeats: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for executor in engines:
        for workers in ([1] if executor == 'serial' else counts):
            samples = []
            for rep in range(repeats + 1):
                stop = threading.Event()
                peak = [rss_bytes()]
                def sample() -> None:
                    while not stop.wait(.01):
                        peak[0] = max(peak[0], rss_bytes())
                monitor = threading.Thread(target=sample, daemon=True)
                before_cpu = time.process_time() + child_cpu()
                monitor.start()
                try:
                    ix, metrics = build_parallel_index(root, executor=executor, workers=workers)
                finally:
                    stop.set()
                    monitor.join()
                cpu = time.process_time() + child_cpu() - before_cpu
                if rep:  # warm-up omitted
                    samples.append((metrics.total_seconds, cpu, peak[0], metrics.merge_seconds))
            rows.append({
                'executor': executor, 'workers': workers,
                'wall_median_s': round(statistics.median(x[0] for x in samples), 5),
                'wall_min_s': round(min(x[0] for x in samples), 5),
                'wall_max_s': round(max(x[0] for x in samples), 5),
                'cpu_median_s': round(statistics.median(x[1] for x in samples), 5),
                'parent_peak_rss_mib': round(max(x[2] for x in samples) / 1048576, 3),
                'merge_median_s': round(statistics.median(x[3] for x in samples), 5),
                'docs': ix.num_docs,
            })
            print(f'{executor:9} {workers:3} workers median={rows[-1]["wall_median_s"]:.3f}s', flush=True)
    baseline = next(r['wall_median_s'] for r in rows if r['executor'] == 'serial')
    for row in rows:
        row['speedup'] = round(baseline / row['wall_median_s'], 3)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('corpus', type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--workers', nargs='+', type=int, default=[1,2,4,8])
    parser.add_argument('--include-all-cpus', action='store_true')
    parser.add_argument('--out', type=Path, default=Path('LAB05_BENCHMARK'))
    args = parser.parse_args()
    if args.repeats < 3: parser.error('at least 3 measured repetitions required')
    cpu_count = os.cpu_count() or 1
    worker_counts = sorted(set(args.workers + ([cpu_count] if args.include_all_cpus else [])))
    if any(n < 1 for n in worker_counts): parser.error('workers must be positive')
    result = benchmark(args.corpus, ['serial', 'threads', 'processes'], worker_counts, args.repeats)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    csv_path = args.out.with_suffix('.csv')
    with csv_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(result[0]))
        writer.writeheader()
        writer.writerows(result)
    metadata = {'platform':platform.platform(), 'processor':platform.processor(), 'logical_cpus':cpu_count, 'python':sys.version, 'gil_enabled':getattr(sys,'_is_gil_enabled',lambda:'unknown')(), 'repeats':args.repeats, 'corpus':str(args.corpus), 'note':'CPU = parent + completed child CPU; RSS = parent only, sampled at 10ms; warmup excluded.'}
    args.out.with_suffix('.json').write_text(json.dumps({'machine':metadata,'results':result},indent=2),encoding='utf-8')
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8,5))
        ax.plot(worker_counts,worker_counts,'--',label='ideal linear')
        for engine in ('threads','processes'):
            records = [r for r in result if r['executor']==engine]
            ax.plot([r['workers'] for r in records],[r['speedup'] for r in records],marker='o',label=engine)
        ax.axhline(1, linestyle=':', label='serial baseline')
        ax.set_xlabel('Workers')
        ax.set_ylabel('Speedup vs serial')
        ax.set_title('Lab 05: indexing speedup')
        ax.legend()
        ax.grid(alpha=.2)
        fig.tight_layout()
        fig.savefig(args.out.with_suffix('.png'),dpi=150)
        plt.close(fig)
    except ImportError:
        print('matplotlib missing; chart not generated. Install matplotlib.',file=sys.stderr)
    print('Saved',csv_path, args.out.with_suffix('.json'))

if __name__ == '__main__':
    main()
