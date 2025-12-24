
import sys
import os
import logging

# Add project root to path
sys.path.append(os.getcwd())

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

from core.database import db_manager
from core.dao import ChecklistDAO
from core.models import Checklist

def test_checklist():
    print("1. Creating Tables...")
    try:
        db_manager.create_tables()
        print("   Tables created (or exist).")
    except Exception as e:
        print(f"   FATAL: Table creation failed: {e}")
        return

    print("\n2. adding Item...")
    try:
        item = ChecklistDAO.add_item("Test Item from Debug Script")
        if item:
            print(f"   Success: Added item ID {item.id}, Text: {item.text}")
        else:
            print("   Failed: Add item returned None")
    except Exception as e:
        print(f"   FATAL: Add item raised exception: {e}")

    print("\n3. Listing Items...")
    try:
        items = ChecklistDAO.get_all()
        print(f"   Found {len(items)} items:")
        for i in items:
            print(f"   - [{i.id}] {i.text} (Done: {i.is_done})")
    except Exception as e:
        print(f"   FATAL: List items failed: {e}")

if __name__ == "__main__":
    test_checklist()
