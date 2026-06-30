"""
重置数据库 — 删旧建新，恢复初始模拟数据

用法:
    python .claude/skills/customer-service/scripts/reset_db.py
    python .claude/skills/customer-service/scripts/reset_db.py --force
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import argparse
from config import DB_PATH, RAG_CHROMA_PATH
from database import init_database
import shutil


def main():
    parser = argparse.ArgumentParser(description="重置客服 Agent 数据库")
    parser.add_argument("--force", action="store_true", help="跳过确认提示")
    args = parser.parse_args()

    if not args.force:
        confirm = input(
            f"⚠️  将删除以下数据:\n"
            f"   - {DB_PATH}\n"
            f"   - {RAG_CHROMA_PATH}/\n"
            f"   确认? [y/N] "
        )
        if confirm.lower() != "y":
            print("已取消")
            return

    # 删除旧数据
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"🗑️  已删除: {DB_PATH}")

    if RAG_CHROMA_PATH.exists():
        shutil.rmtree(RAG_CHROMA_PATH)
        print(f"🗑️  已删除: {RAG_CHROMA_PATH}")

    # 重新初始化
    init_database()
    print("✅ 数据库已重置，模拟数据已恢复")


if __name__ == "__main__":
    main()
