"""ทำให้ import โมดูลใน scripts/ ได้จาก tests/ โดยไม่ต้องลง package"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
