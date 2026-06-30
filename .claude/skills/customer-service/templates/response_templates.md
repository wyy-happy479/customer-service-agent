# 回复模板

> Agent 回复用户时参考以下模板格式。模板中的占位符（`{...}`）由工具返回的 JSON 数据填充。

---

## 订单详情

```
✅ 订单 {order_id} 详情

商品：{product_name}
金额：¥{amount}
状态：{status_label}
下单时间：{created_at}

如需查看物流进度，请告诉我。
```

## 订单列表（按手机号查询）

```
📋 手机号 {phone} 共有 {count} 笔订单：

{for each order:}
  ▸ {order_id}  {product_name}  ¥{amount}  [{status_label}]

如需查看某笔订单详情或物流，请告诉我订单号。
```

## 物流追踪

```
📦 订单 {order_id} 物流进度

快递公司：{carrier}
运单号：{tracking_no}
当前位置：{current_location}
状态：{status_label}

时间线：
{for each event:}
  ● {time}  {status}（{location}）
```

## 退款政策（RAG 结果）

```
📚 关于「{query}」

{for each policy with similarity > 0.70:}
[相关度 {similarity}]
{content}
...

如果您需要为某个订单申请售后，请提供订单号。
```

## 创建工单成功

```
✅ 工单创建成功
工单号：{ticket_id}
类型：{ticket_type_label}
客服将在 24 小时内与您联系处理。
```

## 取消订单 — 高风险确认

```
⚠️ 高风险操作确认

订单：{order_id}
商品：{product_name}
金额：¥{amount}
当前状态：{status_label}

取消订单后无法恢复，是否确认取消？
请输入「确认」继续，或输入其他内容放弃操作。
```

## 操作已取消

```
👌 已取消操作。如有其他需要，请随时告诉我。
```

## 未找到

```
❌ 未找到订单 {order_id}。请确认订单号是否正确。
```

## 参数格式错误

```
❌ {field_name} 格式错误。{help_message}
示例：{example}
```

---

## 状态标签映射

| DB 值 | 展示文字 |
|-------|---------|
| `pending` | 待发货 |
| `shipped` | 已发货 |
| `delivered` | 已签收 |
| `cancelled` | 已取消 |
| `in_transit` | 运输中 |
| `out_for_delivery` | 派送中 |

## 工单类型映射

| DB 值 | 展示文字 |
|-------|---------|
| `refund` | 退款 |
| `exchange` | 换货 |
| `complaint` | 投诉 |
