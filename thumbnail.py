"""Make a 1280x720 thumbnail for a full video: a frame plus the title in bold text.

Run: python thumbnail.py --video full.mp4 --title "My neighbour built a moat" --out thumb.jpg
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

SIZE = (1280, 720)
FONT_CANDIDATES = [
    'C:/Windows/Fonts/ariblk.ttf', 'C:/Windows/Fonts/impact.ttf', 'C:/Windows/Fonts/arialbd.ttf',
    '/System/Library/Fonts/Supplemental/Arial Black.ttf', '/System/Library/Fonts/Supplemental/Impact.ttf',
    '/Library/Fonts/Arial Black.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf', '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf',
]
ACCENT = (255, 212, 0)


def font(size):
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


def frame(video, at_fraction=0.3):
    from make_video import media_duration
    seconds = (media_duration(video) or 10) * at_fraction
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / 'frame.png'
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-y', '-ss', f'{seconds:.2f}', '-i', str(video),
                        '-frames:v', '1', str(target)], check=True)
        return Image.open(target).convert('RGB')


def wrap(draw, text, typeface, width):
    lines, line = [], ''
    for word in text.split():
        candidate = f'{line} {word}'.strip()
        if draw.textlength(candidate, font=typeface) <= width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


def fit_title(draw, title, box_width, max_lines=4):
    """Largest font size at which the title fits in max_lines lines."""
    for size in range(104, 39, -4):
        typeface = font(size)
        lines = wrap(draw, title, typeface, box_width)
        if len(lines) <= max_lines:
            return typeface, lines
    typeface = font(40)
    lines = wrap(draw, title, typeface, box_width)[:max_lines]
    lines[-1] = lines[-1].rstrip('.,') + '…'
    return typeface, lines


def render(background, title):
    image = background.copy()
    scale = max(SIZE[0] / image.width, SIZE[1] / image.height)
    image = image.resize((round(image.width * scale), round(image.height * scale)))
    left, top = (image.width - SIZE[0]) // 2, (image.height - SIZE[1]) // 2
    image = image.crop((left, top, left + SIZE[0], top + SIZE[1]))
    image = ImageEnhance.Brightness(image.filter(ImageFilter.GaussianBlur(3))).enhance(0.55)
    # Darker band on the left keeps the text readable on any background.
    shade = Image.new('L', SIZE, 0)
    ImageDraw.Draw(shade).rectangle((0, 0, 820, SIZE[1]), fill=110)
    image.paste((0, 0, 0), mask=shade.filter(ImageFilter.GaussianBlur(60)))
    draw = ImageDraw.Draw(image)
    typeface, lines = fit_title(draw, title.upper(), 760)
    line_height = typeface.size * 1.12
    y = (SIZE[1] - line_height * len(lines)) / 2
    draw.rectangle((56, y - 8, 70, y + line_height * len(lines) - 8), fill=ACCENT)
    for index, line in enumerate(lines):
        colour = ACCENT if index == 0 else (255, 255, 255)
        draw.text((96, y + index * line_height), line, font=typeface, fill=colour,
                  stroke_width=max(3, typeface.size // 14), stroke_fill=(0, 0, 0))
    return image


def make(video, title, out, image=None):
    background = Image.open(image).convert('RGB') if image else frame(video)
    render(background, title).save(out, 'JPEG', quality=90, optimize=True)
    if Path(out).stat().st_size > 2_000_000:  # YouTube's thumbnail limit
        render(background, title).save(out, 'JPEG', quality=75, optimize=True)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--video', type=Path)
    source.add_argument('--image', type=Path, help='Use this picture instead of a video frame')
    parser.add_argument('--title', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    make(args.video, args.title, args.out, args.image)
    print(f'Saved thumbnail {args.out}', flush=True)


if __name__ == '__main__':
    main()
