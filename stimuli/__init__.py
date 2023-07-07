import pygame


class BaseStim:
    """_summary_"""

    def __init__(self, screen: pygame.surface.Surface, color: str = None) -> None:
        """_summary_

        Args:
            screen (pygame.surface.Surface): _description_
            color (str): _description_
        """
        self.screen = screen
        self.color = color
