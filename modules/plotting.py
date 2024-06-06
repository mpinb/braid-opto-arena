import zmq
import logging
from qtpy import QtCore, QtWidgets
from qtpy.QtCharts import QtCharts
from typing import Optional
import json

logger = logging.getLogger(__name__)


class RealTimePlotter(QtWidgets.QMainWindow):
    def __init__(
        self,
        zmq_port: int = None,
        zmq_context: Optional[zmq.Context] = None,
    ):
        super().__init__()
        self.zmq_port = zmq_port
        self.message_poll_time_ms = 100
        self.sub = None
        self.reset()

    def __del__(self):
        self.unbind()

    def close(self):
        self.unbind()
        super().close()

    def unbind(self):
        # disconnect from all zmq socket
        if self.sub is not None:
            self.sub.unbind(self.sub.LAST_ENDPOINT)
            self.sub.close()
            self.sub = None

        if not self.ctx_given and self.ctx is not None:
            self.ctx.term()
            self.ctx = None

    def reset(self):
        # create a plot to show x-y data
        self.xyplot = QtCharts.QChart()
        self.xyplot.legend().hide()
        self.xyplot.setTitle("X-Y Plot")

    def setup_zmq(self, zmq_context: Optional[zmq.Context] = None):
        """connect to zmq ports and listen to updates"""
        self.ctx_given = zmq_context is not None
        self.ctx = zmq.Context() if zmq_context is None else zmq_context

        # publisher address
        pubilsher_address = f"tcp://127.0.0.1:{self.zmq_port}"

        # subscriber
        self.sub = self.ctx.socket(zmq.SUB)
        self.sub.subscribe("")
        self.sub.bind(pubilsher_address)

        # set timer to poll for messages
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.check_messages)
        self.timer.start(self.message_poll_time_ms)

    def check_messages(
        self, timeout: int = 10, times_to_check: int = 10, do_update: bool = True
    ):
        if self.sub and self.sub.poll(timeout, zmq.POLLIN):
            msg = json.loads(self.sub.recv_string())

            if msg["event"] == "update":
                pass
            elif msg["event"] == "kill":
                self.close()
