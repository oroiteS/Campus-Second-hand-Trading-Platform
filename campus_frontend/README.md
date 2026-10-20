# campus_frontend

校园二手交易平台前端：React 19 + TypeScript（strict）+ Vite + antd 6 + zustand + axios + react-router-dom 7。

## 常用命令

```bash
pnpm install   # 恢复 lockfile 依赖（禁止安装新包）
pnpm gen:api   # 由 ../docs/api/openapi.yaml 生成 src/api/types.ts（契约类型唯一来源）
pnpm lint      # oxlint
pnpm build     # tsc -b && vite build
pnpm dev       # dev server（vite.config.ts 固定端口 5180，代理 /api 与 /socket.io）
```

## 环境变量

复制 `.env.example` 为 `.env`（不入 git）：

| 变量 | 说明 |
| --- | --- |
| `VITE_USE_MOCK` | `true` 走 `src/api/mock/` 契约同构假数据 |
| `VITE_API_BASE` | API 地址；留空走 vite 代理（同源 `/api`） |

## 目录与纪律

- 请求只经 `src/api/`；组件/页面禁止 `fetch` / `axios`
- 契约类型只来自生成物 `src/api/types.ts`；`src/types/` 仅 re-export
- 设计令牌统一定义于 `src/styles/tokens.css`；antd 主题经 `ConfigProvider` 对齐
- 路由表与四态守卫（游客 / 未认证 / 认证学生 / 管理员）集中在 `src/router/`
- 规范基线见 `docs/plan/frontend/00-骨架与契约.md`（效力最高的端内总纲）
