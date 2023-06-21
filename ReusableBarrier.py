import multiprocessing
import time
from multiprocessing import Lock, Process, Semaphore, Value


class ReusableBarrier:
    def __init__(self, n):
        self.n = n
        self.count = Value("i", 0)
        self.mutex = Lock()
        self.barrier = Semaphore(0)

    def wait(self):
        with self.mutex:
            self.count.value += 1
            if self.count.value == self.n:
                self.barrier.release()

        self.barrier.acquire()
        self.barrier.release()


def worker(barrier):
    name = multiprocessing.current_process().name
    while True:
        time.sleep(1)  # simulate work
        print(f"{name} finished work")
        barrier.wait()


if __name__ == "__main__":
    barrier = ReusableBarrier(5)  # use 5 processes

    processes = [
        Process(target=worker, args=(barrier,), name=f"Process-{i}") for i in range(5)
    ]

    for p in processes:
        p.start()

    for p in processes:
        p.join()
