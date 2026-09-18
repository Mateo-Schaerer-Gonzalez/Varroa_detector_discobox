import cv2



class Rect:
    def __init__(self, x1, y1, x2, y2, color=(0, 255, 0), thickness=2, **kwargs):
        # Ensure coordinates are in correct order (x1,y1) top-left, (x2,y2) bottom-right
        self.x1, self.y1 = int(min(x1, x2)), int(min(y1, y2))
        self.x2, self.y2 = int(max(x1, x2)), int(max(y1, y2))
        self.color = color
        self.thickness = thickness

        # set any additional dynamically injected attributes
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def from_config(cls, x1, y1, x2, y2, config):
        style = config.rect_style
        return cls(x1, y1, x2, y2, color=style.color, thickness=style.thickness)

    def draw(self, image, thickness=None):
        thickness = self.thickness if thickness is None else thickness
        cv2.rectangle(image, (self.x1, self.y1), (self.x2, self.y2), self.color, thickness)

    def __contains__(self, other):
        # Return True if other Rect is fully inside this Rect
        return (self.x1 <= other.x1 <= other.x2 <= self.x2 and
                self.y1 <= other.y1 <= other.y2 <= self.y2)

    def contains_point(self, px, py):
        """Return True if the point (px, py) falls within this rect's bounds."""
        return self.x1 <= px <= self.x2 and self.y1 <= py <= self.y2

    def __repr__(self):
        return f"Rect({self.x1}, {self.y1}, {self.x2}, {self.y2})"
    
    def __iter__(self):
        # This makes unpacking possible
        yield self.x1
        yield self.y1
        yield self.x2
        yield self.y2

    def get_ROI(self, frames):
        """
        Extract ROI from frames.
        Supports single image (H, W, C) or batch (N, H, W, C).
        """
        if frames.ndim == 3:  # Single frame
            return frames[self.y1:self.y2, self.x1:self.x2, :]
        elif frames.ndim == 4:  # Multiple frames
            return frames[:, self.y1:self.y2, self.x1:self.x2, :]
        else:
            raise ValueError(f"Expected 3D or 4D array, got {frames.ndim}D")


class TextZone(Rect):
    def __init__(self, x1, y1, x2, y2, text="EMPTY", color=(255, 0, 0), text_color=(0, 0, 255),
                 thickness=2, font_scale=1.0, text_offset_y=10):
        super().__init__(x1, y1, x2, y2, color=color, thickness=thickness)
        self.text = text
        self.color = color
        self.text_color = text_color
        self.font_scale = font_scale
        self.text_offset_y = text_offset_y

    @classmethod
    def from_config(cls, x1, y1, x2, y2, config, text="EMPTY"):
        style = config.text_zone_style
        return cls(x1, y1, x2, y2, text=text, color=style.box_color, text_color=style.text_color,
                    thickness=style.thickness, font_scale=style.font_scale,
                    text_offset_y=style.text_offset_y)

    def draw(self, image, thickness=None, font_scale=None, font=cv2.FONT_HERSHEY_SIMPLEX):
        thickness = self.thickness if thickness is None else thickness
        font_scale = self.font_scale if font_scale is None else font_scale

        # Draw rectangle using Rect's method
        super().draw(image, thickness=thickness)

        # Add text
        cv2.putText(image, self.text, (self.x1, max(self.y1 - self.text_offset_y, 0)),
                    font, font_scale, self.text_color, thickness)

    def __repr__(self):
        return f"TextZone({self.x1}, {self.y1}, {self.x2}, {self.y2}, text='{self.text}')"