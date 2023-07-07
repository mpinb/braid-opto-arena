import pygame

from . import BaseStim


class StaticStim(BaseStim):
    """_summary_

    Args:
        BaseStim (_type_): _description_
    """

    def __init__(self, image: str, *args, **kwargs) -> None:
        """_summary_

        Args:
            image (str): _description_
        """
        super(StaticStim, self).__init__(*args, **kwargs)
        self.image = image
        self.load_image()

    def load_image(self):
        """_summary_"""
        self.bg = pygame.image.load(self.image)
        self.bg = pygame.transform.scale(
            self.bg, (self.screen.get_width(), self.screen.get_height())
        )

    def draw(self):
        """_summary_"""
        self.screen.blit(self.bg, (0, 0))
