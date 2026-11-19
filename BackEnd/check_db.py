import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    import check_db
    if __name__ == "__main__":
        check_db.main()
except ImportError as e:
    print(f"Error importing check_db: {e}")
    sys.exit(1)

