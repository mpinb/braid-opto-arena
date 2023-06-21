from multiprocessing import Barrier, Process, current_process
import time


class ReusableBarrier(Barrier):
    def __init__(self, parties, action=None, timeout=None):
        super().__init__(parties, action, timeout)
        self.initial_parties = parties

    def reset(self):
        super().__init__(self.initial_parties)

    def wait(self):
        super().wait()
        if self.n_waiting == 0:
            self.reset()


def worker(barrier):
    name = current_process().name
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
