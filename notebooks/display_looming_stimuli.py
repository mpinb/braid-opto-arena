import pygame
import sys
from Xlib import display
import os


def get_monitors():
    monitors = []
    d = display.Display()
    screen = d.screen()
    resources = screen.root.xrandr_get_screen_resources()._data

    for output in resources["outputs"]:
        monitor_info = d.xrandr_get_output_info(
            output, resources["config_timestamp"]
        )._data
        if monitor_info["crtc"]:
            crtc = d.xrandr_get_crtc_info(
                monitor_info["crtc"], resources["config_timestamp"]
            )._data
            monitors.append(
                {
                    "name": monitor_info["name"],
                    "x": crtc["x"],
                    "y": crtc["y"],
                    "width": crtc["width"],
                    "height": crtc["height"],
                }
            )
    return monitors


# Initialize Pygame
pygame.init()

# Get available monitors
monitors = get_monitors()

# Print available monitors and ask for selection
print("Available monitors:")
for i, monitor in enumerate(monitors):
    print(
        f"{i + 1}: {monitor['name']} - Position: ({monitor['x']}, {monitor['y']}), Size: {monitor['width']}x{monitor['height']}"
    )

selected_monitor = int(input("Select monitor number: ")) - 1

# Set up the display
width, height = 640, 128
os.environ["SDL_VIDEO_WINDOW_POS"] = (
    f"{monitors[selected_monitor]['x']},{monitors[selected_monitor]['y']}"
)
screen = pygame.display.set_mode((width, height), pygame.NOFRAME)
pygame.display.set_caption("Circles with X positions")

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

# Number of circles
n = 10  # You can change this to any number you want

# Calculate the spacing between circles
spacing = width // (n + 1)

# Font setup
font = pygame.font.Font(None, 24)

# Main game loop
running = True
clock = pygame.time.Clock()

while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Clear the screen
    screen.fill(BLACK)

    # Draw circles and their X positions
    for i in range(0, n + 1):
        x = i * spacing
        y = height // 2

        # Draw circle
        pygame.draw.circle(screen, WHITE, (x, y), 10)

        # Render X position text
        text = font.render(str(x), True, WHITE)
        text_rect = text.get_rect(center=(x, y + 25))
        screen.blit(text, text_rect)

    # Update the display
    pygame.display.flip()

    # Cap the frame rate
    clock.tick(60)

# Quit Pygame
pygame.quit()
sys.exit()
