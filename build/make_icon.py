"""Draws src/keyglow.ico."""
import os
from PIL import Image, ImageDraw

S = 256
img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, S - 8, S - 8), radius=52, fill=(14, 16, 20, 255))
cols = [(0, 240, 255), (43, 107, 255), (160, 32, 255), (255, 31, 168)]
heights = [2, 4, 3, 5, 4, 2]
for i, h in enumerate(heights):
    for r in range(5):
        x = 40 + i * 30
        y = 196 - r * 32
        c = cols[min(3, r)] if r < h else (40, 44, 54)
        d.rounded_rectangle((x, y, x + 24, y + 24), radius=6, fill=c + (255,))
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'keyglow.ico')
img.save(out, sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
print('icon written to', out)
