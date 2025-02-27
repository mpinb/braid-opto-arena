import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from collections import defaultdict
import multiprocessing as mp
from queue import Empty
import time
from datetime import datetime
import requests
import json
from typing import Dict, List, Optional

class AngularVelocityPlotter:
    def __init__(self, braid_url: str = "http://127.0.0.1:8397/",
                 history_length: int = 1000,
                 min_track_duration: float = 1.0):
        """
        Initialize the plotter.
        
        Args:
            braid_url: URL of the braid server
            history_length: Number of points to keep in history
            min_track_duration: Minimum duration (seconds) before plotting an object
        """
        self.braid_url = braid_url
        self.history_length = history_length
        self.min_track_duration = min_track_duration
        
        # Data structures for each object
        self.data: Dict[str, dict] = defaultdict(
            lambda: {
                'timestamps': [],
                'angular_vel': [],
                'first_seen': None,
                'color': None
            }
        )
        
        # Available colors for plotting
        self.colors = plt.cm.tab20(np.linspace(0, 1, 20))
        self.color_idx = 0
        
        # Multiprocessing setup
        self.data_queue = mp.Queue()
        self.process: Optional[mp.Process] = None
        
    def _get_next_color(self) -> np.ndarray:
        """Get the next available color from the colormap."""
        color = self.colors[self.color_idx]
        self.color_idx = (self.color_idx + 1) % len(self.colors)
        return color
        
    def _calculate_angular_velocity(self, xvel: float, yvel: float) -> float:
        """Calculate angular velocity from velocity components."""
        theta = np.arctan2(yvel, xvel)
        return theta  # We'll do unwrapping with accumulated data
        
    def _process_data(self, update_dict: dict):
        """Process incoming data and update the plots."""
        obj_id = update_dict['obj_id']
        timestamp = update_dict['timestamp']
        
        # Initialize object tracking if new
        if self.data[obj_id]['first_seen'] is None:
            self.data[obj_id]['first_seen'] = timestamp
            self.data[obj_id]['color'] = self._get_next_color()
            
        # Add new data point
        self.data[obj_id]['timestamps'].append(timestamp)
        ang_vel = self._calculate_angular_velocity(
            update_dict['xvel'],
            update_dict['yvel']
        )
        self.data[obj_id]['angular_vel'].append(ang_vel)
        
        # Trim history if too long
        if len(self.data[obj_id]['timestamps']) > self.history_length:
            self.data[obj_id]['timestamps'] = self.data[obj_id]['timestamps'][-self.history_length:]
            self.data[obj_id]['angular_vel'] = self.data[obj_id]['angular_vel'][-self.history_length:]
            
    def _update_plot(self, frame):
        """Update function for matplotlib animation."""
        plt.clf()
        
        current_time = time.time()
        
        for obj_id, obj_data in self.data.items():
            # Skip if not enough tracking time
            if obj_data['first_seen'] is None or \
               current_time - obj_data['first_seen'] < self.min_track_duration:
                continue
                
            # Convert timestamps to datetime for better x-axis
            times = [datetime.fromtimestamp(t) for t in obj_data['timestamps']]
            
            if len(obj_data['angular_vel']) > 1:
                # Calculate true angular velocity with unwrap and gradient
                theta_unwrap = np.unwrap(obj_data['angular_vel'])
                angular_velocity = np.gradient(theta_unwrap, dt=0.01)
                
                plt.plot(times, angular_velocity,
                        color=obj_data['color'],
                        label=f'Object {obj_id}')
        
        plt.gcf().autofmt_xdate()  # Rotate and align the tick labels
        plt.xlabel('Time')
        plt.ylabel('Angular Velocity (rad/s)')
        plt.title('Real-time Angular Velocity')
        plt.grid(True)
        plt.legend()
        
        # Try to get new data without blocking
        try:
            while True:  # Process all available updates
                update_dict = self.data_queue.get_nowait()
                self._process_data(update_dict)
        except Empty:
            pass
            
    def _data_collection_process(self):
        """Process for collecting data from braid server."""
        session = requests.session()
        events_url = self.braid_url + "events"
        
        try:
            response = session.get(
                events_url,
                stream=True,
                headers={"Accept": "text/event-stream"}
            )
            
            for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                try:
                    lines = chunk.strip().split("\n")
                    if len(lines) != 2 or not lines[1].startswith("data: "):
                        continue
                        
                    data = json.loads(lines[1][len("data: "):])
                    update_dict = data["msg"].get("Update")
                    
                    if update_dict:
                        self.data_queue.put(update_dict)
                except Exception as e:
                    print(f"Error processing chunk: {e}")
                    
        except Exception as e:
            print(f"Connection error: {e}")
            
    def start(self):
        """Start the plotter."""
        # Start data collection process
        self.process = mp.Process(target=self._data_collection_process)
        self.process.start()
        
        # Set up the plot
        plt.ion()  # Enable interactive mode
        fig = plt.figure(figsize=(12, 6))
        ani = FuncAnimation(fig, self._update_plot,
                          interval=50,  # 50ms refresh rate
                          blit=False)
        
        plt.show()
        
    def stop(self):
        """Stop the plotter and cleanup."""
        if self.process:
            self.process.terminate()
            self.process.join()
        plt.close('all')

if __name__ == "__main__":
    # Example usage as standalone script
    plotter = AngularVelocityPlotter()
    try:
        plotter.start()
        input("Press Enter to stop...")  # Keep the script running
    except KeyboardInterrupt:
        pass
    finally:
        plotter.stop()