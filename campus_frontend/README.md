# campus_frontend

校园二手交易平台前端：React 19 + TypeScript（strict）+ Vite + antd 6 + zustand + axios + react-router-dom 7。

## 常用命令

```bash
pnpm install   # 恢复 lockfile 依赖（禁止安装新包）
pnpm gen:api   # 由 ../docs/api/openapi.yaml 生成 src/api/types.ts（契约类型唯一来源）
pnpm lint      # oxlint
pnpm build     # tsc -b && vite build
pnpm dev       # dev server（vite.config.ts 固定 127.0.0.1:5180，代理 /api 与 /socket.io）
```

## 环境变量

复制 `.env.example` 为 `.env`（不入 git）：

| 变量 | 作用域 | 说明 |
| --- | --- | --- |
| `VITE_USE_MOCK` | 构建期 | `true` 走 `src/api/mock/` 契约同构假数据；`false`/留空走真实接口 |
| `VITE_API_BASE` | 构建期 | axios 的 `baseURL`，**含 `/api` 后缀**。留空 = 同源 `/api`（dev 下经 vite 代理）；跨域直连填 `http://host:port/api`。**不要填纯主机地址**（会缺 `/api` 前缀） |
| `VITE_PROXY_TARGET` | 仅 dev server | `/api` 与 `/socket.io` 的代理目标，默认 `http://127.0.0.1:5010`；不进入构建产物 |

两者语义独立、不可混用：`VITE_API_BASE` 决定浏览器**请求发往哪里**（会被打进产物），
`VITE_PROXY_TARGET` 只决定 dev server **把 `/api` 转发到哪里**。dev 联调的推荐姿势是
`VITE_API_BASE` 留空（走同源 `/api`）+ `VITE_PROXY_TARGET` 指向后端。

dev server 显式绑定 `127.0.0.1:5180`（`server.host: '127.0.0.1'`），联调一律使用 `127.0.0.1` 字面地址。

## 目录与纪律

- 请求只经 `src/api/`；组件/页面禁止 `fetch` / `axios`
- 契约类型只来自生成物 `src/api/types.ts`；`src/types/` 仅 re-export
- 设计令牌统一定义于 `src/styles/tokens.css`；antd 主题经 `ConfigProvider` 对齐
- 路由表与四态守卫（游客 / 未认证 / 认证学生 / 管理员）集中在 `src/router/`
- 规范基线见 `docs/plan/frontend/00-骨架与契约.md`（效力最高的端内总纲）
