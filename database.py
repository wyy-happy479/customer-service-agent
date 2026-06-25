"""
数据库模块 — SQLite 模拟数据库

📖 核心概念：
    用 SQLite 模拟真实客服系统的数据库。SQLite 是一个文件型数据库，
    不需要安装服务器，数据就是一个 .db 文件，非常适合学习和原型开发。

🔍 底层原理：
    SQLite 把整个数据库（表结构 + 数据）存在一个文件里。
    当你执行 SQL 查询时，它直接读写这个文件，没有网络开销。
    所以它是"零配置"的——不需要 `pip install mysql`、不需要启动服务。

💡 为什么用 SQLite 而不是字典？
    - 字典存内存，程序关了数据就没了 → SQLite 持久化
    - 字典没有 SQL 查询能力 → SQLite 支持 WHERE/JOIN/ORDER BY
    - 面试时你说"用 SQLite 做本地模拟库"比"写了个 dict"专业得多
"""

import sqlite3
import json
from pathlib import Path
from config import DB_PATH


def get_connection():
    """获取数据库连接（自动创建文件如果不存在）"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # 让查询结果可以用 dict 方式访问
    return conn


def init_database():
    """
    初始化数据库：建表 + 插入模拟数据。

    表结构说明：
    - orders:     订单表（订单号、用户、商品、金额、状态）
    - logistics:  物流表（订单号、快递公司、运单号、当前位置、时间线）
    - tickets:    工单表（工单号、订单号、类型、状态、创建时间）

    真实业务中这些东西分散在不同的微服务里，
    但原理一样——Agent 调工具 → 工具查对应的数据库/API。
    """
    conn = get_connection()
    cursor = conn.cursor()

    # ============================================================
    # 1. 订单表
    # ============================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,       -- 如 ORD-0001
            customer_name TEXT NOT NULL,         -- 客户姓名
            customer_phone TEXT NOT NULL,        -- 手机号
            product_name TEXT NOT NULL,          -- 商品名
            amount REAL NOT NULL,                -- 金额
            status TEXT NOT NULL,                -- pending/shipped/delivered/cancelled
            created_at TEXT NOT NULL             -- 下单时间
        )
    """)

    # ============================================================
    # 2. 物流表
    # ============================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS logistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,        -- 关联订单号
            carrier TEXT NOT NULL,                -- 快递公司
            tracking_no TEXT NOT NULL,            -- 快递单号
            current_location TEXT NOT NULL,       -- 当前位置
            status TEXT NOT NULL,                 -- in_transit/out_for_delivery/delivered
            timeline TEXT NOT NULL,               -- JSON 格式的物流时间线
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    """)

    # ============================================================
    # 3. 售后工单表
    # ============================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT UNIQUE NOT NULL,       -- 如 TK-0001
            order_id TEXT NOT NULL,               -- 关联订单号
            ticket_type TEXT NOT NULL,            -- refund/exchange/complaint
            description TEXT,                     -- 问题描述
            status TEXT NOT NULL,                 -- open/processing/closed
            created_at TEXT NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    """)

    # ============================================================
    # 插入模拟数据（仅在表为空时插入）
    # ============================================================
    cursor.execute("SELECT COUNT(*) FROM orders")
    if cursor.fetchone()[0] == 0:
        _insert_mock_data(cursor)

    conn.commit()
    conn.close()
    print("✅ 数据库初始化完成")


def _insert_mock_data(cursor):
    """插入模拟数据——模拟一个真实电商的订单+物流系统"""

    # ---- 订单数据 ----
    orders = [
        ("ORD-0001", "张三", "13800138001", "机械键盘 K99", 299.00,
         "shipped", "2025-06-20 10:30:00"),
        ("ORD-0002", "李四", "13900139002", "蓝牙耳机 Pro", 599.00,
         "delivered", "2025-06-18 14:20:00"),
        ("ORD-0003", "王五", "13700137003", "27寸显示器 4K", 2499.00,
         "pending", "2025-06-25 09:15:00"),
        ("ORD-0004", "赵六", "13600136004", "人体工学椅", 1899.00,
         "shipped", "2025-06-22 16:45:00"),
        ("ORD-0005", "孙七", "13500135005", "无线鼠标 M3", 199.00,
         "cancelled", "2025-06-19 11:00:00"),
        ("ORD-0006", "张三", "13800138001", "笔记本支架", 89.00,
         "delivered", "2025-06-15 08:30:00"),
    ]
    cursor.executemany(
        "INSERT INTO orders (order_id, customer_name, customer_phone, "
        "product_name, amount, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        orders,
    )

    # ---- 物流数据 ----
    logistics = [
        ("ORD-0001", "顺丰速运", "SF1234567890", "北京分拣中心",
         "in_transit",
         json.dumps([
             {"time": "2025-06-20 18:00", "status": "已揽收", "location": "深圳龙华网点"},
             {"time": "2025-06-21 02:00", "status": "已到达中转站", "location": "广州分拣中心"},
             {"time": "2025-06-22 08:00", "status": "运输中", "location": "北京分拣中心"},
         ], ensure_ascii=False)),
        ("ORD-0002", "京东物流", "JD9876543210", "上海浦东新区",
         "delivered",
         json.dumps([
             {"time": "2025-06-18 16:00", "status": "已揽收", "location": "上海松江网点"},
             {"time": "2025-06-19 09:00", "status": "派送中", "location": "上海浦东新区"},
             {"time": "2025-06-19 14:30", "status": "已签收", "location": "上海浦东新区XX大厦"},
         ], ensure_ascii=False)),
        ("ORD-0004", "中通快递", "ZTO1122334455", "武汉中转站",
         "in_transit",
         json.dumps([
             {"time": "2025-06-22 19:00", "status": "已揽收", "location": "杭州余杭网点"},
             {"time": "2025-06-23 06:00", "status": "运输中", "location": "武汉中转站"},
         ], ensure_ascii=False)),
        ("ORD-0006", "圆通速递", "YT5544332211", "北京朝阳区",
         "delivered",
         json.dumps([
             {"time": "2025-06-15 10:00", "status": "已揽收", "location": "北京海淀网点"},
             {"time": "2025-06-16 09:00", "status": "派送中", "location": "北京朝阳区"},
             {"time": "2025-06-16 15:20", "status": "已签收", "location": "北京朝阳区XX小区"},
         ], ensure_ascii=False)),
    ]
    cursor.executemany(
        "INSERT INTO logistics (order_id, carrier, tracking_no, "
        "current_location, status, timeline) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        logistics,
    )

    # ---- 已有工单 ----
    tickets = [
        ("TK-0001", "ORD-0005", "refund", "商品与描述不符，申请退款",
         "closed", "2025-06-20 09:00:00"),
    ]
    cursor.executemany(
        "INSERT INTO tickets (ticket_id, order_id, ticket_type, "
        "description, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        tickets,
    )

    print("  📦 已插入 6 条订单 + 4 条物流 + 1 条工单数据")


# ============================================================
# 对外查询接口 — 这些就是工具函数真正调用的数据访问层
# ============================================================

def query_order(order_id: str) -> dict | None:
    """按订单号查询订单详情"""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM orders WHERE order_id = ?", (order_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return dict(row)


def query_orders_by_phone(phone: str) -> list[dict]:
    """按手机号查询用户的所有订单"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM orders WHERE customer_phone = ? ORDER BY created_at DESC",
        (phone,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def query_logistics(order_id: str) -> dict | None:
    """按订单号查询物流信息"""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM logistics WHERE order_id = ?", (order_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    result = dict(row)
    result["timeline"] = json.loads(result["timeline"])
    return result


def cancel_order(order_id: str) -> dict:
    """
    取消订单。
    只有 pending 状态的订单可以取消（还没发货）。
    已发货的订单取消会失败。
    """
    conn = get_connection()
    # 先查状态
    order = conn.execute(
        "SELECT * FROM orders WHERE order_id = ?", (order_id,)
    ).fetchone()

    if order is None:
        conn.close()
        return {"success": False, "message": f"订单 {order_id} 不存在"}

    if order["status"] == "cancelled":
        conn.close()
        return {"success": False, "message": f"订单 {order_id} 已经被取消了"}

    if order["status"] in ("shipped", "delivered"):
        conn.close()
        return {
            "success": False,
            "message": f"订单 {order_id} 当前状态为「{order['status']}」，"
                       f"已发货/已完成的订单无法取消。请联系人工客服处理。"
        }

    # 可以取消
    conn.execute(
        "UPDATE orders SET status = 'cancelled' WHERE order_id = ?",
        (order_id,)
    )
    conn.commit()
    conn.close()
    return {
        "success": True,
        "message": f"订单 {order_id} 已成功取消，款项将在 3-5 个工作日内原路退回。"
    }


def create_ticket(order_id: str, ticket_type: str, description: str) -> dict:
    """创建售后工单"""
    conn = get_connection()

    # 检查订单是否存在
    order = conn.execute(
        "SELECT * FROM orders WHERE order_id = ?", (order_id,)
    ).fetchone()
    if order is None:
        conn.close()
        return {"success": False, "message": f"订单 {order_id} 不存在"}

    # 生成工单号
    count = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    ticket_id = f"TK-{count + 1:04d}"

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        "INSERT INTO tickets (ticket_id, order_id, ticket_type, "
        "description, status, created_at) VALUES (?, ?, ?, ?, 'open', ?)",
        (ticket_id, order_id, ticket_type, description, now)
    )
    conn.commit()
    conn.close()

    return {
        "success": True,
        "ticket_id": ticket_id,
        "message": f"工单 {ticket_id} 已创建，类型：{ticket_type}。"
                   f"客服将在 24 小时内与您联系。"
    }


if __name__ == "__main__":
    # 直接运行此文件 → 初始化数据库
    init_database()
    print("\n📊 数据预览：")

    conn = get_connection()
    for table in ["orders", "logistics", "tickets"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count} 条记录")
    conn.close()
