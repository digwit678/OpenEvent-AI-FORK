
import sys
import os
import pytest

@pytest.mark.v4
def test_print_path():
    print("\nSYS.PATH:")
    for p in sys.path:
        print(p)
    
    try:
        import detection
        print(f"\nDETECTION MODULE: {detection}")
        if hasattr(detection, '__file__'):
            print(f"DETECTION FILE: {detection.__file__}")
        if hasattr(detection, '__path__'):
            print(f"DETECTION PATH: {detection.__path__}")
    except ImportError as e:
        print(f"\nIMPORT ERROR: {e}")
