# 数据库 Schema（SQLite 模拟库）

## 表结构

### orders — 订单表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK AUTOINCREMENT | 内部主键 |
| order_id | TEXT | UNIQUE NOT NULL | 订单号，格式 `ORD-XXXX` |
| customer_name | TEXT | NOT NULL | 客户姓名 |
| customer_phone | TEXT | NOT NULL | 手机号（11位） |
| product_name | TEXT | NOT NULL | 商品名称 |
| amount | REAL | NOT NULL | 金额（元） |
| status | TEXT | NOT NULL | `pending` / `shipped` / `delivered` / `cancelled` |
| created_at | TEXT | NOT NULL | 下单时间 `YYYY-MM-DD HH:MM:SS` |

### logistics — 物流表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK AUTOINCREMENT | 内部主键 |
| order_id | TEXT | UNIQUE NOT NULL, FK→orders | 关联订单号 |
| carrier | TEXT | NOT NULL | 快递公司 |
| tracking_no | TEXT | NOT NULL | 快递单号 |
| current_location | TEXT | NOT NULL | 当前位置 |
| status | TEXT | NOT NULL | `in_transit` / `out_for_delivery` / `delivered` |
| timeline | TEXT | NOT NULL | JSON 数组格式的物流时间线 |

**timeline JSON 格式：**
```json
[
  {"time": "2025-06-20 18:00", "status": "已揽收", "location": "深圳龙华网点"},
  {"time": "2025-06-21 02:00", "status": "已到达中转站", "location": "广州分拣中心"},
  {"time": "2025-06-22 08:00", "status": "运输中", "location": "北京分拣中心"}
]
```

### tickets — 售后工单表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK AUTOINCREMENT | 内部主键 |
| ticket_id | TEXT | UNIQUE NOT NULL | 工单号，格式 `TK-XXXX` |
| order_id | TEXT | NOT NULL, FK→orders | 关联订单号 |
| ticket_type | TEXT | NOT NULL | `refund` / `exchange` / `complaint` |
| description | TEXT | — | 问题描述 |
| status | TEXT | NOT NULL | `open` / `processing` / `closed` |
| created_at | TEXT | NOT NULL | 创建时间 |

---

## 模拟数据

| order_id | 客户 | 商品 | 金额 | 状态 |
|----------|------|------|------|------|
| ORD-0001 | 张三 | 机械键盘 K99 | ¥299 | shipped |
| ORD-0002 | 李四 | 蓝牙耳机 Pro | ¥599 | delivered |
| ORD-0003 | 王五 | 27寸显示器 4K | ¥2,499 | pending |
| ORD-0004 | 赵六 | 人体工学椅 | ¥1,899 | shipped |
| ORD-0005 | 孙七 | 无线鼠标 M3 | ¥199 | cancelled |
| ORD-0006 | 张三 | 笔记本支架 | ¥89 | delivered |

---

## 查询接口

| 函数 | SQL | 说明 |
|------|-----|------|
| `query_order(id)` | `SELECT * FROM orders WHERE order_id = ?` | 单条订单 |
| `query_orders_by_phone(phone)` | `SELECT * FROM orders WHERE customer_phone = ? ORDER BY created_at DESC` | 用户全部订单 |
| `query_logistics(id)` | `SELECT * FROM logistics WHERE order_id = ?` | 物流信息 |
| `cancel_order(id)` | `UPDATE orders SET status = 'cancelled' WHERE order_id = ? AND status = 'pending'` | 取消订单 |
| `create_ticket(oid, type, desc)` | `INSERT INTO tickets (...) VALUES (?, ?, ?, 'open', ?)` | 创建工单 |
