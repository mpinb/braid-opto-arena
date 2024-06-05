import zmq
import json
import sys
import numpy as np
from collections import deque
from qtpy.QtWidgets import QApplication
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import logging

# Parameters
N = 100  # Number of elements to plot

# Initialize deque for storing the data
frames = deque(maxlen=N)
x_data = deque(maxlen=N)
y_data = deque(maxlen=N)
xvel_data = deque(maxlen=N)
yvel_data = deque(maxlen=N)
angular_velocity_data = deque(maxlen=N)

# Setup ZMQ context and SUB socket
context = zmq.Context()
socket = context.socket(zmq.SUB)
socket.connect("tcp://localhost:12345")
socket.setsockopt_string(zmq.SUBSCRIBE, "")

# Initialize the Qt application
app = QApplication(sys.argv)

# Initialize the Matplotlib figure and axes
fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8))

# Set up the axes
ax1.set_title("X-Y Position")
ax1.set_xlim(0, 10)
ax1.set_ylim(0, 10)
ax1.set_xlabel("X")
ax1.set_ylabel("Y")

ax2.set_title("Linear Velocity")
ax2.set_xlim(0, N)
ax2.set_ylim(-1, 1)
ax2.set_xlabel("Frame")
ax2.set_ylabel("Velocity")

ax3.set_title("Angular Velocity")
ax3.set_xlim(0, N)
ax3.set_ylim(-np.pi, np.pi)
ax3.set_xlabel("Frame")
ax3.set_ylabel("Angular Velocity")

# Line objects for updating the plot
(line1,) = ax1.plot([], [], "bo")
(line2,) = ax2.plot([], [], "r-")
(line3,) = ax3.plot([], [], "g-")


# Function to initialize the plot
def init():
    line1.set_data([], [])
    line2.set_data([], [])
    line3.set_data([], [])
    return line1, line2, line3


# Function to update the plot
def update(frame):
    while True:
        try:
            message = socket.recv_string(zmq.NOBLOCK)

            if message == "kill":
                logging.info("plotter received kill message, shutting down.")
                plt.close(fig)
                return line1, line2, line3
            else:
                data = json.loads(message)

            frames.append(data["frame"])
            x_data.append(data["x"])
            y_data.append(data["y"])
            xvel_data.append(data["xvel"])
            yvel_data.append(data["yvel"])
            angular_velocity = np.arctan2(data["yvel"], data["xvel"])
            angular_velocity_data.append(angular_velocity)

        except zmq.Again:
            break

    line1.set_data(x_data, y_data)
    line2.set_data(frames, xvel_data)
    line3.set_data(frames, angular_velocity_data)
    return line1, line2, line3


# Create animation
ani = FuncAnimation(fig, update, init_func=init, blit=True, interval=100)

# Start the Qt event loop
plt.show()
app.exec()
