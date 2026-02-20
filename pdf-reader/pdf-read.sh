#!/usr/bin/env bash
# PDF Reader - Marker + Vision extraction
# Usage: pdf-read.sh <pdf-path> [--marker-only|--vision-only] [--pages N]

set -euo pipefail

PDF_PATH="${1:-}"
MODE="full"
MAX_PAGES=10

# Parse args
shift || true
while [[ $# -gt 0 ]]; do
    case $1 in
        --marker-only) MODE="marker" ;;
        --vision-only) MODE="vision" ;;
        --pages) MAX_PAGES="$2"; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
    shift
done

if [[ -z "$PDF_PATH" ]]; then
    echo "Usage: pdf-read.sh <pdf-path> [--marker-only|--vision-only] [--pages N]"
    exit 1
fi

if [[ ! -f "$PDF_PATH" ]]; then
    echo "Error: File not found: $PDF_PATH"
    exit 1
fi

# Setup
PDF_NAME=$(basename "$PDF_PATH" .pdf)
OUTPUT_DIR="/tmp/pdf-reader/${PDF_NAME}-$(date +%s)"
mkdir -p "$OUTPUT_DIR/pages"

VENV="$HOME/.local/share/pdf-tools"
MARKER_BIN="$VENV/bin/marker_single"

echo "=== PDF Reader ==="
echo "Input: $PDF_PATH"
echo "Output: $OUTPUT_DIR"
echo "Mode: $MODE"
echo ""

# --- MARKER EXTRACTION ---
if [[ "$MODE" == "full" || "$MODE" == "marker" ]]; then
    echo ">>> Running Marker extraction..."
    
    if [[ -x "$MARKER_BIN" ]]; then
        # Run marker with explicit output dir
        "$MARKER_BIN" "$PDF_PATH" --output_format markdown --output_dir "$OUTPUT_DIR" 2>&1 | tail -10
        
        # Find the markdown output (marker creates subdir with PDF name)
        MD_FILE=$(find "$OUTPUT_DIR" -name "*.md" -type f ! -name "content.md" | head -1)
        if [[ -n "$MD_FILE" ]]; then
            cp "$MD_FILE" "$OUTPUT_DIR/content.md"
        fi
        
        if [[ -f "$OUTPUT_DIR/content.md" ]]; then
            echo "✓ Marker output: $OUTPUT_DIR/content.md"
            echo "  $(wc -l < "$OUTPUT_DIR/content.md") lines"
        else
            echo "⚠ No markdown generated"
        fi
    else
        echo "⚠ Marker not found at $MARKER_BIN"
        echo "  Run: source $VENV/bin/activate && marker_single $PDF_PATH"
    fi
    echo ""
fi

# --- PAGE IMAGE EXTRACTION ---
if [[ "$MODE" == "full" || "$MODE" == "vision" ]]; then
    echo ">>> Extracting page images..."
    
    if command -v pdftoppm &>/dev/null; then
        pdftoppm -png -r 150 -l "$MAX_PAGES" "$PDF_PATH" "$OUTPUT_DIR/pages/page"
        PAGE_COUNT=$(ls "$OUTPUT_DIR/pages/"*.png 2>/dev/null | wc -l)
        echo "✓ Extracted $PAGE_COUNT page images"
    else
        echo "⚠ pdftoppm not found. Install: sudo apt install poppler-utils"
        echo "  Skipping vision extraction"
    fi
    echo ""
fi

# --- SUMMARY ---
echo "=== Output ==="
ls -la "$OUTPUT_DIR/" 2>/dev/null || true
echo ""
echo "Content: $OUTPUT_DIR/content.md"
echo "Pages:   $OUTPUT_DIR/pages/"
echo ""
echo "To analyze with vision, use OpenClaw image tool on page PNGs."
