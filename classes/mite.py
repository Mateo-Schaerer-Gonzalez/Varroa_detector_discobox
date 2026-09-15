from rect import TextZone


class Mite(TextZone):
    """Mite object that handles bounding boxes """
    id_counter = 0 # Class variable to assign unique IDs

    def __init__(self, x1, y1, x2, y2, color=(0, 0, 255)):
        super().__init__(x1, y1, x2, y2, color, text=f"mite_{Mite.id_counter:04d}")
        self.alive = True


print(Mite(10, 20, 30, 40).text)  # Example usage


