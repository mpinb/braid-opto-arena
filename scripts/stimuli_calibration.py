import os

import pygame

os.environ["SDL_VIDEO_WINDOW_POS"] = "%d,%d" % (0, 0)

# Initialize Pygame
pygame.init()

# Set the dimensions of the screen
screen_width = 640
screen_height = 128

# Set the number of circles and their radius
num_circles = 20
circle_radius = 30

# Calculate the horizontal spacing between circles
horizontal_spacing = screen_width // num_circles

# Create the screen
screen = pygame.display.set_mode((screen_width, screen_height), pygame.NOFRAME)

# Set the background color
background_color = (255, 255, 255)  # White
screen.fill(background_color)

# Set the circle color
circle_color = (255, 0, 0)  # Red

# Set the font and font size for the circle labels
font = pygame.font.Font(None, 30)

stimuli_position = list(range(0, 640 + 32, 32))

# Calculate the x-position of the circle
x = stimuli_position[20]
print(x)

# Calculate the y-position of the circle
y = screen_height // 2

# Draw the circle
pygame.draw.circle(screen, circle_color, (int(x), y), circle_radius)

# Create a text surface with the x-position label
text_surface = font.render(str(int(x)), True, (0, 0, 0))  # Black

# Calculate the position of the text to center it within the circle
text_rect = text_surface.get_rect(center=(int(x), y))

# Draw the text surface onto the screen
screen.blit(text_surface, text_rect)

# Update the screen
pygame.display.flip()

# Run the game loop
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

# Quit Pygame
pygame.quit()
