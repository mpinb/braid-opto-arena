import sys
from PyQt5 import QtWidgets
import pyqtgraph as pg
from PyQt5.QtCore import QTimer
import zmq
from collections import deque


class RealTimePlot(QtWidgets.QMainWindow):
    def __init__(self, *args, **kwargs):
        super(RealTimePlot, self).__init__(*args, **kwargs)

        # Create a central widget and set a horizontal layout for the two plots
        self.centralWidget = QtWidgets.QWidget()
        self.setCentralWidget(self.centralWidget)
        self.layout = QtWidgets.QHBoxLayout()
        self.centralWidget.setLayout(self.layout)

        # Set up the ZMQ subscriber
        self.context = zmq.Context()
        self.subscriber = self.context.socket(zmq.SUB)
        self.subscriber.connect(
            "tcp://localhost:12345"
        )  # Connect to the publisher's address
        self.subscriber.setsockopt_string(zmq.SUBSCRIBE, "")  # Subscribe to all topics

        # Create two PlotWidget instances for scatter plots
        self.graphWidget1 = pg.PlotWidget()
        self.graphWidget2 = pg.PlotWidget()
        self.layout.addWidget(self.graphWidget1)
        self.layout.addWidget(self.graphWidget2)

        # Initialize data lists for each plot
        self.x = deque(maxlen=100)
        self.y = deque(maxlen=100)
        self.z = deque(maxlen=100)

        # Configure the first graph for scatter plot
        self.graphWidget1.setBackground("w")
        self.graphWidget1.setTitle("Real-time Data for Y", color="b", size="30pt")
        self.graphWidget1.setLabel("left", "Y-Axis", color="red", size=20)
        self.graphWidget1.setLabel("bottom", "Time (X)", color="red", size=20)
        self.graphWidget1.showGrid(x=True, y=True)

        # Configure the second graph for scatter plot
        self.graphWidget2.setBackground("w")
        self.graphWidget2.setTitle("Real-time Data for Z", color="b", size="30pt")
        self.graphWidget2.setLabel("left", "Z-Axis", color="red", size=20)
        self.graphWidget2.setLabel("bottom", "Time (X)", color="red", size=20)
        self.graphWidget2.showGrid(x=True, y=True)

        # Set up a timer to check for new data
        self.timer = QTimer()
        self.timer.setInterval(50)  # 50 ms update interval
        self.timer.timeout.connect(self.update_plot_data)
        self.timer.start()

    def update_plot_data(self):
        try:
            # Check for new data from ZMQ
            message = self.subscriber.recv(zmq.NOBLOCK)  # Non-blocking
            t, y, z = map(float, message.decode().split())
            self.x.append(t)
            self.y.append(y)
            self.z.append(z)
            self.graphWidget1.clear()  # Clear previous scatter points
            self.graphWidget2.clear()  # Clear previous scatter points
            self.graphWidget1.plot(
                self.x, self.y, pen=None, symbol="o", symbolBrush="r"
            )
            self.graphWidget2.plot(
                self.x, self.z, pen=None, symbol="o", symbolBrush="b"
            )
        except zmq.Again:
            pass  # No new data


def main():
    app = QtWidgets.QApplication(sys.argv)
    main = RealTimePlot()
    main.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
