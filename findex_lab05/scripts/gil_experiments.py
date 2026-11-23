"""Lab 05 quick experiments: CPU vs I/O, switch interval and data race.

Run as a script so spawn workers can safely import __main__.
"""
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from threading import Lock, Thread
from time import perf_counter, sleep
import sys


def cpu_task(n: int) -> int:
    return sum(i * i for i in range(n))


def io_task(seconds: float) -> None:
    sleep(seconds)


def measure(label: str, function) -> None:
    start = perf_counter()
    function()
    print(f'{label:25} {perf_counter() - start:.3f}s')


def lost_update(use_lock: bool) -> int:
    shared = [0]
    lock = Lock()
    def worker() -> None:
        for _ in range(5_000):
            if use_lock:
                with lock:
                    shared[0] += 1
            else:
                # Explicit yield between read and write creates a reproducible race.
                current = shared[0]
                sleep(0)
                shared[0] = current + 1
    threads = [Thread(target=worker) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    return shared[0]


def main() -> None:
    print('GIL enabled:', getattr(sys, '_is_gil_enabled', lambda: 'unknown')())
    print('switch interval:', sys.getswitchinterval())
    n = 1_000_000
    measure('one CPU task', lambda: cpu_task(n))
    measure('two CPU sequential', lambda: [cpu_task(n) for _ in range(2)])
    for cls in [ThreadPoolExecutor, ProcessPoolExecutor]:
        def execute() -> None:
            with cls(max_workers=2) as pool:
                list(pool.map(cpu_task, [n,n]))
        measure('two CPU '+cls.__name__, execute)
    measure('two I/O sequential', lambda: [io_task(.2) for _ in range(2)])
    with ThreadPoolExecutor(max_workers=2) as pool:
        measure('two I/O threads', lambda: list(pool.map(io_task, [.2,.2])))
    print('race without lock:',lost_update(False),'(expected 10000)')
    print('race with lock:',lost_update(True),'(expected 10000)')
    original = sys.getswitchinterval()
    try:
        sys.setswitchinterval(.0001)
        measure('threads tiny interval', lambda: run_threads(n))
    finally:
        sys.setswitchinterval(original)
    print('A ProcessPoolExecutor lambda cannot be pickled; use module-level functions.')


def run_threads(n: int) -> None:
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(cpu_task,[n,n]))

if __name__ == '__main__': main()
