#!/usr/bin/env python3
"""
Test script to verify inline image rendering in terminal.
Run this script directly in your terminal to see if images render inline.
"""

import os
import sys
import base64
import tempfile
from pathlib import Path

# Create a sample chart image for testing
def create_sample_chart():
    """Create a sample matplotlib chart for testing."""
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    
    # Create a simple chart
    fig, ax = plt.subplots(figsize=(8, 6))
    x = [1, 2, 3, 4, 5]
    y = [10, 25, 30, 45, 50]
    ax.plot(x, y, marker='o', linewidth=2, markersize=8)
    ax.set_title('Test Sales Chart')
    ax.set_xlabel('Month')
    ax.set_ylabel('Sales ($)')
    ax.grid(True, alpha=0.3)
    
    # Save to temp file
    temp_dir = tempfile.mkdtemp()
    chart_path = os.path.join(temp_dir, 'test_chart.png')
    fig.savefig(chart_path, dpi=100, bbox_inches='tight')
    plt.close(fig)
    
    return chart_path


def test_terminal_detection():
    """Test terminal detection."""
    print("=" * 60)
    print("TERMINAL DETECTION TEST")
    print("=" * 60)
    
    term = os.environ.get("TERM_PROGRAM", "")
    term_lower = term.lower()
    
    print(f"TERM_PROGRAM: {term}")
    print(f"TERM: {os.environ.get('TERM', '')}")
    print(f"KITTY_WINDOW_ID: {os.environ.get('KITTY_WINDOW_ID', 'not set')}")
    print(f"")
    print(f"stdout.isatty(): {sys.stdout.isatty()}")
    print(f"stderr.isatty(): {sys.stderr.isatty()}")
    print(f"stdin.isatty(): {sys.stdin.isatty()}")
    print(f"")
    print(f"sys.__stdout__ is sys.stdout: {sys.__stdout__ is sys.stdout}")
    print(f"sys.__stdout__.closed: {sys.__stdout__.closed if sys.__stdout__ else 'N/A'}")
    print("")
    
    # Check terminal type
    is_iterm2 = term in ("iTerm.app", "WezTerm", "Hyper", "vscode") or "iterm" in term_lower or "wezterm" in term_lower or term_lower == "vscode"
    is_kitty = term_lower == "kitty" or os.environ.get("KITTY_WINDOW_ID")
    
    print(f"Should use iTerm2 protocol: {is_iterm2}")
    print(f"Should use Kitty protocol: {is_kitty}")
    print("")


def test_dev_tty():
    """Test /dev/tty access."""
    print("=" * 60)
    print("/dev/tty ACCESS TEST")
    print("=" * 60)
    
    try:
        with open("/dev/tty", "w") as tty:
            tty.write("Test write to /dev/tty successful!\n")
            tty.flush()
        print("✓ /dev/tty is accessible and writable")
    except Exception as e:
        print(f"✗ /dev/tty failed: {e}")
    print("")


def test_inline_image_rendering(chart_path: str):
    """Test inline image rendering."""
    print("=" * 60)
    print("INLINE IMAGE RENDERING TEST")
    print("=" * 60)
    print(f"Chart file: {chart_path}")
    print(f"File size: {os.path.getsize(chart_path)} bytes")
    print("")
    print("Attempting to render image inline...")
    print("")
    
    # Read the image
    with open(chart_path, "rb") as f:
        image_data = f.read()
    
    b64 = base64.b64encode(image_data).decode("ascii")
    term = os.environ.get("TERM_PROGRAM", "")
    term_lower = term.lower()
    
    # Try to get terminal
    try:
        if sys.__stdout__ and not sys.__stdout__.closed:
            tty = sys.__stdout__
        else:
            tty = open("/dev/tty", "w")
    except:
        tty = sys.stdout
    
    # iTerm2 protocol
    if term in ("iTerm.app", "WezTerm", "Hyper", "vscode") or "iterm" in term_lower or "wezterm" in term_lower or term_lower == "vscode":
        name_b64 = base64.b64encode(os.path.basename(chart_path).encode()).decode()
        seq = (
            f"\033]1337;File=inline=1;size={len(image_data)};"
            f"name={name_b64};width=auto;preserveAspectRatio=1:{b64}\a"
        )
        tty.write(f"\r\n{seq}\r\n")
        tty.flush()
        print("✓ Sent iTerm2 protocol escape codes")
        print("")
        print(">>> CHECK ABOVE - Did you see the image? <<<")
    
    # Kitty protocol
    elif term_lower == "kitty" or os.environ.get("KITTY_WINDOW_ID"):
        chunk_size = 4096
        chunks = [b64[i:i + chunk_size] for i in range(0, len(b64), chunk_size)]
        tty.write("\r\n")
        for i, chunk in enumerate(chunks):
            m = 1 if i < len(chunks) - 1 else 0
            if i == 0:
                tty.write(f"\033_Ga=T,f=100,m={m};{chunk}\033\\")
            else:
                tty.write(f"\033_Gm={m};{chunk}\033\\")
        tty.write("\r\n")
        tty.flush()
        print("✓ Sent Kitty protocol escape codes")
        print("")
        print(">>> CHECK ABOVE - Did you see the image? <<<")
    
    else:
        print(f"✗ Unknown terminal type: {term}")
        print("Falling back to file path...")
        tty.write(f"\r\nChart saved: {chart_path}\r\n")
        tty.flush()
    
    print("")


def test_ascii_art(chart_path: str):
    """Test ASCII art rendering as fallback."""
    print("=" * 60)
    print("ASCII ART RENDERING TEST (FALLBACK)")
    print("=" * 60)
    
    try:
        from PIL import Image
        import io
        
        img = Image.open(chart_path)
        
        # Resize for terminal
        img = img.resize((80, 40), Image.LANCZOS)
        
        # Convert to grayscale
        img = img.convert('L')
        
        # Get pixels
        pixels = img.load()
        width, height = img.size
        
        # ASCII characters from dark to light
        chars = ' .:-=+*#%@'
        
        # Build ASCII art
        ascii_art = []
        for y in range(height):
            row = ''
            for x in range(width):
                pixel = pixels[x, y]
                char_index = int(pixel / 256 * len(chars))
                char_index = min(char_index, len(chars) - 1)
                row += chars[char_index]
            ascii_art.append(row)
        
        print('\n'.join(ascii_art))
        print("")
        print("✓ ASCII art rendered successfully")
    except ImportError:
        print("✗ PIL not installed - cannot test ASCII art")
        print("  Install with: pip install pillow")
    except Exception as e:
        print(f"✗ ASCII art failed: {e}")
    print("")


def main():
    print("\n" + "=" * 60)
    print("INLINE IMAGE RENDERING TEST SUITE")
    print("=" * 60)
    print("")
    
    # Run tests
    test_terminal_detection()
    test_dev_tty()
    
    # Create sample chart
    print("Creating sample chart...")
    chart_path = create_sample_chart()
    print(f"Chart created: {chart_path}")
    print("")
    
    # Test inline rendering
    test_inline_image_rendering(chart_path)
    
    # Test ASCII art fallback
    test_ascii_art(chart_path)
    
    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
If you saw the image above with the iTerm2/Kitty test:
  ✓ Inline rendering is working!

If you didn't see the image but saw ASCII art:
  ✓ ASCII art fallback is working!

If you saw neither:
  ✗ There may be a terminal compatibility issue.
    Try running in a different terminal (iTerm2, WezTerm, Kitty)
""")
    
    # Cleanup
    os.remove(chart_path)
    print(f"Test chart removed: {chart_path}")


if __name__ == "__main__":
    main()