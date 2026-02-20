# PDF Reader Skill

Extract content AND visual styling from PDFs using Marker + Vision analysis.

**Two-pass extraction:**
1. **Marker** → structured markdown (text, tables, headings, layout)
2. **Vision** → styling analysis (colors, fonts, design patterns)

## Setup (One-Time)

### 1. Install Dependencies

```bash
# Create Python venv with marker
uv venv ~/.local/share/pdf-tools
source ~/.local/share/pdf-tools/bin/activate
uv pip install marker-pdf pdf2image pillow psutil

# Install poppler for page images
sudo apt install poppler-utils  # Debian/Ubuntu
brew install poppler            # macOS
```

### 2. Download the Script

```bash
# Create skill directory
mkdir -p ~/.openclaw/workspace/skills/pdf-reader
cd ~/.openclaw/workspace/skills/pdf-reader

# Download pdf-read.sh
curl -O https://skills.sb28.ai/pdf-reader/pdf-read.sh
chmod +x pdf-read.sh

# Symlink for easy access
ln -sf ~/.openclaw/workspace/skills/pdf-reader/pdf-read.sh ~/.local/bin/pdf-read
```

## Usage

```bash
# Full analysis (marker + vision pages)
pdf-read /path/to/document.pdf

# Text extraction only (faster)
pdf-read /path/to/document.pdf --marker-only

# Limit pages for vision (large PDFs)
pdf-read /path/to/document.pdf --pages 5
```

## Output

Creates `/tmp/pdf-reader/<filename>-<timestamp>/`:
- `content.md` — Marker's structured markdown extraction
- `pages/` — Individual page images (PNG)

## Integration with OpenClaw

After running `pdf-read`, use OpenClaw's tools:

```
# Read the extracted content
read /tmp/pdf-reader/<output>/content.md

# Analyze styling with vision
image /tmp/pdf-reader/<output>/pages/page-1.png "Analyze the visual design..."
```

## What It's Good For

- **Proposals** — Extract content + study design patterns
- **Contracts** — Get structured text for review
- **Reports** — Tables and data preserved as markdown
- **Design inspiration** — Analyze typography, colors, layout

## Requirements

- Python 3.10+
- `uv` (recommended) or `pip`
- `poppler-utils` (for page image extraction)
- ~1GB disk for Marker models (downloads on first run)

## Troubleshooting

**Marker hangs on first run?**
It's downloading models (~1GB). Wait 1-2 minutes.

**No page images?**
Install poppler: `sudo apt install poppler-utils`

**Permission denied?**
Make script executable: `chmod +x pdf-read.sh`

---

*Created by [SB28](https://sb28.ai) • Feb 2026*
