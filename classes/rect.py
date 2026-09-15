import cv2



class Rect:
    def __init__(self, x1, y1, x2, y2, color=(0, 255, 0)):
        # Ensure coordinates are in correct order (x1,y1) top-left, (x2,y2) bottom-right
        self.x1, self.y1 = min(x1, x2), min(y1, y2)
        self.x2, self.y2 = max(x1, x2), max(y1, y2)
        self.color = color
       
    def draw(self, image, thickness=2):
        cv2.rectangle(image, (self.x1, self.y1), (self.x2, self.y2), self.color, thickness)

    def __contains__(self, other):
        # Return True if other Rect is fully inside this Rect
        return (self.x1 <= other.x1 <= other.x2 <= self.x2 and
                self.y1 <= other.y1 <= other.y2 <= self.y2)

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
    def __init__(self, x1, y1, x2, y2, text="EMPTY", color=(255, 0, 0)):
        super().__init__(x1, y1, x2, y2)
        self.text = text
        self.color = color


    def draw(self, image, thickness=2, font_scale=1, font=cv2.FONT_HERSHEY_SIMPLEX):
        # Draw rectangle using Rect's method
        super().draw(image, thickness=thickness)


        # Add text
        cv2.putText(image, self.text, (self.x1, max(self.y1 - 10, 0)),
                    font, font_scale, (0,0,255), thickness)
        
    def __repr__(self):
        return f"TextZone({self.x1}, {self.y1}, {self.x2}, {self.y2}, text='{self.text}')"