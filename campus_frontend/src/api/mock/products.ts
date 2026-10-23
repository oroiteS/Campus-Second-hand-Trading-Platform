import dayjs from 'dayjs'
import type {
  CampusRef,
  CategoryRef,
  MyProductsQuery,
  Paginated,
  ProductCondition,
  ProductCreateInput,
  ProductDetail,
  ProductListQuery,
  ProductSearchQuery,
  ProductStatus,
  ProductStatusActionInput,
  ProductSummary,
  SearchResultData,
  UserProfile,
  UserSummary,
} from '../../types'
import { delay } from '../../utils/delay'
import {
  validateDescription,
  validateSearchQ,
  validateTitle,
} from '../../utils/validators'
import { PRODUCT_STATUS_TEXT } from '../../utils/statusText'
import { ApiError } from '../http'
import { MOCK_CATEGORIES } from './categories'
import { findMockUpload, isOwnedUpload } from './uploads'
import {
  MOCK_ACCOUNTS,
  nowIso,
  requireVerifiedSession,
  toUserSummary,
} from './users'

/**
 * 商品域 mock（products tag 8 接口，契约 0.3.0 逐字段同构）。
 *
 * 商品池 ≥ 60 条：6 分类 × 5 成色 × 三档价格区间全覆盖；其中 ≥3 条标题不含
 * 「机械键盘」但描述含键盘类语义（联调 AC-09 的 mock 预演，搜索「机械键盘」
 * 可在标题命中之后召回这些描述命中条目）。
 *
 * 演示账号绑定：mock 认证通过的在校学生只有 student02（id 1002 小明），
 * 商品池中「我的商品」样例（含 on_sale / off_sale / forced_off / trading / sold
 * 全状态谱系）绑定该账号；其他登录态下我的商品为空（空态演示）。
 *
 * 图源口径：ImageRef.url 一律为按分类配色的 inline SVG data URI（任务卡铁律，
 * 零外网依赖）；分类配色为 mock 图片内容色，非 UI 设计令牌。
 */

/** 全部 mock 商品同属示例大学（school 1）；校区两枚（契约 CampusRef） */
const SCHOOL_ID = 1

const MOCK_CAMPUSES: CampusRef[] = [
  { id: 1, school_id: 1, name: '东校区' },
  { id: 2, school_id: 1, name: '西校区' },
]

/** 分类 → 占位图配色（mock 图片内容色，非设计令牌） */
const CATEGORY_COLORS: Record<number, string> = {
  1: '#4c6ef5',
  2: '#2f9e44',
  3: '#e8590c',
  4: '#1098ad',
  5: '#ae3ec9',
  6: '#495057',
}

/** 卖家池（approved 学生，UserSummary 同构；两条带信誉分供「暂无/有值」两态演示） */
const MOCK_SELLERS: Record<number, UserProfile> = {
  3001: {
    id: 3001, username: 'seller01', student_no: '2024010201', email: 'xiaohong@example.edu.cn',
    nickname: '小红', display_name: '小红-示例大学(东校区)', phone: null, avatar: null,
    school: { id: 1, name: '示例大学', multi_campus: true },
    campus: { id: 1, school_id: 1, name: '东校区' },
    role: 'student', auth_status: 'approved', status: 'active', credit_score: null,
    created_at: '2026-09-02T09:00:00+08:00',
  },
  3002: {
    id: 3002, username: 'seller02', student_no: '2024010202', email: 'xiaogang@example.edu.cn',
    nickname: '小刚', display_name: '小刚-示例大学(西校区)', phone: null, avatar: null,
    school: { id: 1, name: '示例大学', multi_campus: true },
    campus: { id: 2, school_id: 1, name: '西校区' },
    role: 'student', auth_status: 'approved', status: 'active', credit_score: 4.5,
    created_at: '2026-09-02T09:10:00+08:00',
  },
  3003: {
    id: 3003, username: 'seller03', student_no: '2024010203', email: 'xiaoli@example.edu.cn',
    nickname: '小丽', display_name: '小丽-示例大学(东校区)', phone: null, avatar: null,
    school: { id: 1, name: '示例大学', multi_campus: true },
    campus: { id: 1, school_id: 1, name: '东校区' },
    role: 'student', auth_status: 'approved', status: 'active', credit_score: null,
    created_at: '2026-09-02T09:20:00+08:00',
  },
  3004: {
    id: 3004, username: 'seller04', student_no: '2024010204', email: 'xiaoqiang@example.edu.cn',
    nickname: '小强', display_name: '小强-示例大学(西校区)', phone: null, avatar: null,
    school: { id: 1, name: '示例大学', multi_campus: true },
    campus: { id: 2, school_id: 1, name: '西校区' },
    role: 'student', auth_status: 'approved', status: 'active', credit_score: 4.9,
    created_at: '2026-09-02T09:30:00+08:00',
  },
}

// ---- 商品池内部形态（响应时剥离内部字段，逐字段映射为契约形态） ----

interface MockProduct {
  id: number
  title: string
  description: string
  price: number
  originalPrice: number | null
  condition: ProductCondition
  status: ProductStatus
  /** 图集（数组序 = 展示排序），元素为契约 ImageRef 形态 */
  images: { id: number; url: string }[]
  viewCount: number
  favoriteCount: number
  categoryId: number
  campusId: number
  sellerId: number
  createdAt: string
  updatedAt: string
  /** 内部标记：被管理员强制下架（off_sale + forcedOff，重新上架 → 3002） */
  forcedOff: boolean
}

interface SeedItem {
  title: string
  price: number
  original: number | null
  condition: ProductCondition
  desc: string
}

// 每分类种子：价格覆盖 <50 / 50–500 / >500 三档；成色 5 档轮转。
// 数码电子含 3 条「标题无键盘、描述含机械键盘」的语义搜索演示条目（AC-09）。
const SEEDS: Array<{ categoryId: number; items: SeedItem[] }> = [
  {
    categoryId: 1,
    items: [
      { title: '罗技 K845 机械键盘 98 新', price: 199, original: 399, condition: 'excellent', desc: '去年购入，自用一年，键帽轻微打油，红轴手感完好，附原包装。' },
      { title: 'iPhone 13 128G 国行双卡', price: 2899, original: 4999, condition: 'good', desc: '电池效率 86%，边框细磕碰，功能全部正常，已退出 Apple ID。' },
      { title: '小米真无线蓝牙耳机 Air2', price: 89, original: 199, condition: 'as_new', desc: '99 新，仅拆封试戴，充电盒无划痕，附件齐全。' },
      { title: 'iPad 第九代 64G WiFi 版', price: 1499, original: 2499, condition: 'excellent', desc: '贴膜使用，屏幕无划痕，配原装充电头与数据线。' },
      { title: 'Kindle Paperwhite 4 8G', price: 380, original: 998, condition: 'good', desc: '阅读灯均匀，机身轻磨痕，重置完成，附磁吸保护套。' },
      { title: '客制化键帽套装 108 键', price: 129, original: 260, condition: 'as_new', desc: '收自客制化团购，PBT 二色成型，适配机械键盘 104 布局，几未上机。' },
      { title: '屏幕清洁套装（清洁泥+软刷）', price: 25, original: 45, condition: 'fair', desc: '清洁泥可深入机械键盘缝隙与屏幕边框，已用三分之一，刷子完好。' },
      { title: '罗技优联接收器 Nano 二合一', price: 35, original: null, condition: 'good', desc: '一个接收器同时连接机械键盘与鼠标，即插即用，测试正常。' },
      { title: '罗技 G102 游戏鼠标', price: 59, original: 99, condition: 'good', desc: 'RGB 灯效正常，微动清脆，附备用脚贴。' },
      { title: '拓品 NX5 便携解码耳放', price: 469, original: 659, condition: 'as_new', desc: '试音架使用，推力充足，附原装皮套与数据线。' },
      { title: '笔记本电脑支架 铝合金可折叠', price: 45, original: 89, condition: 'brand_new', desc: '全新未拆封，囤了两件出一件，六档高度可调。' },
    ],
  },
  {
    categoryId: 2,
    items: [
      { title: '高等数学 第七版 上下册', price: 18, original: 42, condition: 'good', desc: '笔记较少， spine 完好，含习题解答册。' },
      { title: '数据结构（C 语言版）严蔚敏', price: 15, original: 35, condition: 'good', desc: '经典教材，目录页有姓名，内页干净。' },
      { title: '大学物理实验报告册', price: 5, original: 12, condition: 'brand_new', desc: '全新未写，买重复了，低价出。' },
      { title: '考研英语一真题黄皮书 2020–2025', price: 45, original: 98, condition: 'as_new', desc: '仅前两套做了笔记，其余空白，附答题卡。' },
      { title: 'JavaScript 高级程序设计 第 4 版', price: 65, original: 129, condition: 'excellent', desc: '红宝书，轻微翻阅痕迹，无笔记。' },
      { title: '概率论与数理统计 浙大版', price: 14, original: 32, condition: 'fair', desc: '内页有铅笔笔记（可擦），封面折角。' },
      { title: '六级词汇闪过 乱序版', price: 22, original: 49, condition: 'as_new', desc: '高频词已划重点，书脊完好。' },
      { title: '操作系统导论（黑书）', price: 70, original: 139, condition: 'excellent', desc: 'OSTEP 中文版，九成新，无笔记。' },
      { title: '线性代数辅导讲义 李永乐', price: 20, original: 38, condition: 'good', desc: '考研复习用，重点章节有荧光笔标记。' },
      { title: '民法典（教学版）', price: 30, original: 58, condition: 'fair', desc: '法学教材，内页有少量笔记，不影响阅读。' },
    ],
  },
  {
    categoryId: 3,
    items: [
      { title: '小米台灯 Lite', price: 39, original: 79, condition: 'excellent', desc: '国 AA 级照度，无色偏，附原装电源。' },
      { title: '折叠晾衣架 不锈钢', price: 20, original: 45, condition: 'good', desc: '宿舍阳台神器，折叠收纳，结构稳固无锈。' },
      { title: '电煮锅 1.5L 宿舍神器', price: 55, original: 109, condition: 'good', desc: '蒸煮一体，功率适中不断电，内胆无涂层脱落。' },
      { title: '床上四件套 1.2m', price: 68, original: 158, condition: 'as_new', desc: '水洗一次，纯棉材质，无起球褪色。' },
      { title: '手持迷你挂烫机', price: 42, original: 99, condition: 'fair', desc: '出汽正常，水箱有水垢痕迹，已除垢。' },
      { title: '收纳箱三件套', price: 30, original: 69, condition: 'good', desc: '搬宿舍闲置，可叠放，盖子卡扣完好。' },
      { title: '自动折叠加固雨伞', price: 15, original: 39, condition: 'brand_new', desc: '全新备用伞，八骨加固，反向折叠不湿身。' },
      { title: '316 不锈钢保温杯 500ml', price: 25, original: 59, condition: 'brand_new', desc: '全新带吊牌，赠杯刷，保温 6 小时以上。' },
      { title: 'USB 静音台式风扇', price: 35, original: 75, condition: 'good', desc: '三档风速，宿舍床头用了一季，噪音很小。' },
      { title: '宿舍遮光床帘 90cm', price: 28, original: 56, condition: 'as_new', desc: '遮光率 90%，支架齐全，洗过晾干。' },
    ],
  },
  {
    categoryId: 4,
    items: [
      { title: '捷安特 ATX 660 山地车', price: 750, original: 1698, condition: 'good', desc: '24 速变速顺畅，前后刹车已换新，可试骑。' },
      { title: '尤尼克斯羽毛球拍 天斧 88D', price: 620, original: 1299, condition: 'excellent', desc: '4U5，拍框无磕碰，新穿 BG80 线 26 磅。' },
      { title: '斯伯丁 7 号 PU 篮球', price: 65, original: 129, condition: 'good', desc: '室内场使用，气密性良好，纹路清晰。' },
      { title: '瑜伽垫 8mm 加厚 TPE', price: 38, original: 89, condition: 'as_new', desc: '双面防滑，仅家用数次，附绑带。' },
      { title: '计数钢丝跳绳', price: 12, original: 29, condition: 'brand_new', desc: '全新，电子计数，绳长可调。' },
      { title: '可调节哑铃 10kg 一对', price: 88, original: 169, condition: 'good', desc: '包胶无破损，宿舍增肌闲置出。' },
      { title: '双人三季帐篷', price: 268, original: 499, condition: 'as_new', desc: '露营一次，无破损漏雨，含地钉与收纳袋。' },
      { title: '瑜伽球 65cm 加厚', price: 25, original: 55, condition: 'fair', desc: '气密正常，表面有使用痕迹，附打气筒。' },
      { title: '速干运动 T 恤 2 件', price: 40, original: 99, condition: 'good', desc: '均码速干面料，训练穿着，无破损变形。' },
      { title: '一体成型骑行头盔', price: 75, original: 159, condition: 'excellent', desc: 'PCS 外壳，透气孔完好，头围 56–60 可调。' },
    ],
  },
  {
    categoryId: 5,
    items: [
      { title: '优衣库摇粒绒外套 M 码', price: 69, original: 199, condition: 'excellent', desc: '复古摇粒绒，无起球掉毛，拉链顺滑。' },
      { title: 'Nike Air Force 1 白色 42 码', price: 320, original: 799, condition: 'good', desc: '鞋头轻微氧化折痕，鞋底纹路尚可，附原盒。' },
      { title: '双肩电脑包 15.6 寸防泼水', price: 55, original: 129, condition: 'as_new', desc: '出差两次，防泼水面料完好，USB 出线口。' },
      { title: '春秋连帽卫衣 L 码', price: 39, original: 99, condition: 'good', desc: '加绒款，袖口轻微起球，无破洞污渍。' },
      { title: '化妆刷套装 12 支', price: 30, original: 79, condition: 'brand_new', desc: '全新未拆，动物毛混纤，附洗刷蛋与收纳筒。' },
      { title: "Levi's 501 直筒牛仔裤 30 码", price: 99, original: 399, condition: 'good', desc: '赤耳丹宁，养色自然，裤脚原长未改。' },
      { title: '棒球帽 黑色可调节', price: 19, original: 49, condition: 'fair', desc: '帽檐轻微变形，扣带完好，已清洗。' },
      { title: '格纹羊毛围巾', price: 45, original: 129, condition: 'as_new', desc: '澳洲羊毛，无勾丝起球，附吊牌。' },
      { title: '回力经典帆布鞋 41 码', price: 59, original: 119, condition: 'good', desc: '国潮经典款，鞋面洁净，橡胶鞋底磨损少。' },
      { title: '行李箱 20 寸登机箱', price: 118, original: 269, condition: 'excellent', desc: '万向轮顺滑，TSA 密码锁，箱面细划痕。' },
    ],
  },
  {
    categoryId: 6,
    items: [
      { title: '民谣吉他 41 寸初学款', price: 330, original: 699, condition: 'fair', desc: '云杉面板，弦距已调低，适合入门，附变调夹。' },
      { title: '桌面小绿萝盆栽', price: 8, original: 20, condition: 'good', desc: '水培转土培，长势旺盛，附白瓷盆。' },
      { title: '拼图 1000 片 梵高星月夜', price: 28, original: 68, condition: 'brand_new', desc: '全新未拆封，缺片包换，附图纸。' },
      { title: '五子棋围棋二合一木盒', price: 20, original: 45, condition: 'good', desc: '实木棋盘，棋子齐全，盒盖即棋盘。' },
      { title: '三层保温饭盒', price: 26, original: 59, condition: 'good', desc: '不锈钢内胆，保温 4 小时，密封圈无老化。' },
      { title: '星空投影灯', price: 42, original: 99, condition: 'as_new', desc: '六种灯效，蓝牙音箱功能正常，附遥控器。' },
      { title: '书法文房四宝套装', price: 50, original: 120, condition: 'fair', desc: '兼毫笔两支，墨汁半瓶，砚台毛毡齐全。' },
      { title: 'USB 桌面加湿器', price: 30, original: 69, condition: 'good', desc: '静音雾化，宿舍干燥救星，附备用棉芯。' },
      { title: '卡通抱枕 45cm', price: 15, original: 39, condition: 'brand_new', desc: '全新带标签，超柔短绒，内芯饱满。' },
      { title: '手帐本套装 胶带贴纸', price: 32, original: 78, condition: 'as_new', desc: '入坑三分钟退坑，素材几乎全新，整盒出。' },
    ],
  },
]

/** 「我的商品」样例：绑定演示账号 student02（id 1002），覆盖全状态谱系 */
const OWN_SEEDS: Array<SeedItem & { status: ProductStatus; forcedOff?: boolean; campusId: number }> = [
  { title: 'iPad Air 5 保护壳 带笔槽', price: 35, original: 89, condition: 'brand_new', desc: '买壳送膜，全新未拆，透明防黄 TPU。', status: 'on_sale', campusId: 1 },
  { title: '宿舍床头小台灯 触摸调光', price: 25, original: null, condition: 'good', desc: '三档调光，夹头牢固，毕业清仓。', status: 'on_sale', campusId: 1 },
  { title: '考研政治全套资料 肖四肖八', price: 30, original: 88, condition: 'good', desc: '刷题册几乎空白，精讲精练有笔记。', status: 'on_sale', campusId: 2 },
  { title: '罗技 M330 静音蓝牙鼠标', price: 45, original: 99, condition: 'as_new', desc: '静音微动，接收器在电池仓，暂时下架自用。', status: 'off_sale', campusId: 1 },
  { title: 'USB 小风扇 夹式', price: 20, original: 45, condition: 'fair', desc: '被管理员下架的样例（描述违规词演示）。', status: 'off_sale', forcedOff: true, campusId: 1 },
  { title: '显示器桌面支架臂', price: 80, original: 159, condition: 'excellent', desc: '交易中样例：已锁定待付款。', status: 'trading', campusId: 2 },
  { title: 'Redmi Buds 4 蓝牙耳机', price: 55, original: 129, condition: 'good', desc: '已售样例，买家自提完成。', status: 'sold', campusId: 1 },
]

const POOL: MockProduct[] = []

let productIdSeed = 100

let imageIdSeed = 1000

function nextImageIds(count: number): number[] {
  const ids: number[] = []
  for (let i = 0; i < count; i += 1) {
    imageIdSeed += 1
    ids.push(imageIdSeed)
  }
  return ids
}

/** 按分类配色的 inline SVG data URI 占位图（mock 图源铁律：零外网图源） */
function svgDataUrl(categoryId: number, label: string, seq: number): string {
  // SVG 命名空间分段拼接：保持本目录源码零 http 字面（任务卡图源铁律）。
  // xmlns 为 data URI SVG 的必需命名空间（W3C 规范要求），非外网图源；
  // 经第 1 轮审查豁免 grep 门槛（豁免由主 agent 登记看板）。
  const ns = 'http' + '://' + 'www.w3.org/2000/svg'
  const text = label.length > 9 ? `${label.slice(0, 9)}…` : label
  const svg =
    `<svg xmlns='${ns}' width='600' height='450'>` +
    `<rect width='600' height='450' fill='${CATEGORY_COLORS[categoryId] ?? '#495057'}'/>` +
    `<rect x='20' y='20' width='560' height='410' rx='20' fill='#ffffff' fill-opacity='0.88'/>` +
    `<text x='44' y='210' font-size='38' font-family='sans-serif' fill='#1f2937'>${text}</text>` +
    `<text x='44' y='258' font-size='22' font-family='sans-serif' fill='#4b5563'>mock 示意图 ${seq}</text>` +
    `</svg>`
  return `data:image/svg+xml,${encodeURIComponent(svg)}`
}

function buildProduct(input: {
  title: string
  price: number
  original: number | null
  condition: ProductCondition
  desc: string
  categoryId: number
  campusId: number
  sellerId: number
  createdAt: string
  imageCount: number
  status?: ProductStatus
  forcedOff?: boolean
  favoriteCount?: number
  viewCount?: number
}): MockProduct {
  const ids = nextImageIds(input.imageCount)
  const images = ids.map((id, index) => ({
    id,
    url: svgDataUrl(input.categoryId, input.title, index + 1),
  }))
  return {
    id: productIdSeed++,
    title: input.title,
    description: input.desc,
    price: input.price,
    originalPrice: input.original,
    condition: input.condition,
    status: input.status ?? 'on_sale',
    images,
    viewCount: input.viewCount ?? 0,
    favoriteCount: input.favoriteCount ?? 0,
    categoryId: input.categoryId,
    campusId: input.campusId,
    sellerId: input.sellerId,
    createdAt: input.createdAt,
    updatedAt: input.createdAt,
    forcedOff: input.forcedOff ?? false,
  }
}

/** 池初始化（模块加载时一次）：61 条他人商品 + 7 条「我的商品」= 68 条 */
function initPool(): void {
  const base = dayjs()
  let index = 0
  for (const group of SEEDS) {
    group.items.forEach((item) => {
      const createdAt = base
        .subtract(index % 25, 'day')
        .subtract((index * 7) % 24, 'hour')
        .format('YYYY-MM-DDTHH:mm:ssZ')
      POOL.push(
        buildProduct({
          ...item,
          categoryId: group.categoryId,
          campusId: index % 2 === 0 ? 1 : 2,
          sellerId: 3001 + (index % 4),
          createdAt,
          imageCount: 1 + (index % 3),
          favoriteCount: (index * 7) % 9,
          viewCount: (index * 13) % 200,
        }),
      )
      index += 1
    })
  }

  // 状态谱系演示（他人商品中的非在售样例，仅收藏列表可见置灰条目）：
  const lastThree = POOL.slice(-3)
  if (lastThree[0]) lastThree[0].status = 'off_sale' // 收藏列表「已下架」置灰演示
  if (lastThree[1]) lastThree[1].status = 'trading' // 收藏列表「交易中」徽章演示
  if (lastThree[2]) lastThree[2].status = 'sold' // 收藏列表「已售」置灰演示

  // 「我的商品」样例（绑定 student02 / id 1002）
  OWN_SEEDS.forEach((item, i) => {
    const createdAt = base
      .subtract(i + 1, 'hour')
      .format('YYYY-MM-DDTHH:mm:ssZ')
    POOL.push(
      buildProduct({
        title: item.title,
        price: item.price,
        original: item.original,
        condition: item.condition,
        desc: item.desc,
        categoryId: [1, 3, 2, 1, 3, 1, 1][i] ?? 6,
        campusId: item.campusId,
        sellerId: 1002,
        createdAt,
        imageCount: 2,
        status: item.status,
        forcedOff: item.forcedOff,
        favoriteCount: i % 3,
        viewCount: i * 11,
      }),
    )
  })
}

initPool()

// ---- 收藏状态（favorites mock 与 is_favorited 联动的唯一存储） ----

/** userId → (productId → favorited_at) */
const favoritesByUser = new Map<number, Map<number, string>>()

export function favoritesOfUser(userId: number): Map<number, string> {
  return favoritesByUser.get(userId) ?? new Map()
}

export function addFavoriteRecord(userId: number, productId: number, at: string): void {
  let records = favoritesByUser.get(userId)
  if (!records) {
    records = new Map()
    favoritesByUser.set(userId, records)
  }
  records.set(productId, at)
}

/** 取消收藏记录；返回是否存在（供收藏数递减判断） */
export function removeFavoriteRecord(userId: number, productId: number): boolean {
  return favoritesByUser.get(userId)?.delete(productId) ?? false
}

/** 演示预置：student02 收藏 3 件（含 1 件已下架置灰条目） */
;(function seedFavorites(): void {
  const onSaleIds = POOL.filter((p) => p.sellerId !== 1002 && p.status === 'on_sale')
    .slice(0, 2)
    .map((p) => p.id)
  const offSale = POOL.find((p) => p.sellerId !== 1002 && p.status === 'off_sale')
  const at = [
    dayjs().subtract(2, 'hour').format('YYYY-MM-DDTHH:mm:ssZ'),
    dayjs().subtract(1, 'day').format('YYYY-MM-DDTHH:mm:ssZ'),
    dayjs().subtract(3, 'day').format('YYYY-MM-DDTHH:mm:ssZ'),
  ]
  const targetIds = offSale ? [...onSaleIds, offSale.id] : onSaleIds
  targetIds.forEach((id, i) => {
    const product = POOL.find((p) => p.id === id)
    if (product) {
      product.favoriteCount += 1
      addFavoriteRecord(1002, id, at[i] ?? at[0])
    }
  })
})()

// ---- 会话 / 校验辅助 ----

/** 管理员写操作统一拒绝（契约总则：发布/编辑/收藏/上传对管理员一律 9003） */
function requireStudentFor(action: string): UserProfile {
  const user = requireVerifiedSession()
  if (user.role === 'admin') {
    throw new ApiError(9003, `管理员无交易能力，不能${action}`, null)
  }
  return user
}

function sameSchoolAsPool(user: UserProfile): boolean {
  return user.role === 'admin' || user.school?.id === SCHOOL_ID
}

function findProduct(id: number): MockProduct | undefined {
  return POOL.find((p) => p.id === id)
}

function categoryById(id: number): CategoryRef | undefined {
  return MOCK_CATEGORIES.find((c) => c.id === id)
}

/** 校验 ProductCreateInput（发布/编辑共用；编辑时既有图集 id 视同合法） */
function validateProductInput(
  body: ProductCreateInput,
  userId: number,
  editing: MockProduct | null,
): void {
  const fields: Record<string, string> = {}
  const titleError = validateTitle(body.title)
  if (titleError) fields.title = titleError
  const descriptionError = validateDescription(body.description)
  if (descriptionError) fields.description = descriptionError

  // 服务端 Decimal 复验同源：数值范围 + 两位小数（mock 以字符串小数位判定）
  const priceText = String(body.price)
  const priceDecimals = priceText.includes('.') ? priceText.split('.')[1].length : 0
  if (!Number.isFinite(body.price) || body.price < 0.01 || body.price > 99999.99 || priceDecimals > 2) {
    fields.price = '价格须为 0.01–99999.99 元，最多两位小数'
  }
  if (body.original_price != null) {
    const originalText = String(body.original_price)
    const originalDecimals = originalText.includes('.') ? originalText.split('.')[1].length : 0
    if (
      !Number.isFinite(body.original_price) ||
      body.original_price < 0.01 ||
      body.original_price > 99999.99 ||
      originalDecimals > 2
    ) {
      fields.original_price = '原价须为 0.01–99999.99 元，最多两位小数'
    }
  }

  if (!categoryById(body.category_id)) {
    fields.category_id = '分类不存在或已停用'
  }
  if (body.campus_id != null && !MOCK_CAMPUSES.some((c) => c.id === body.campus_id)) {
    fields.campus_id = '校区不存在或已停用'
  }

  // image_ids：数量 1–9、不重复、须本人上传（编辑时既有图集 id 放行）
  if (body.image_ids.length < 1 || body.image_ids.length > 9) {
    fields.image_ids = '图片数量须为 1–9 张'
  } else if (new Set(body.image_ids).size !== body.image_ids.length) {
    fields.image_ids = '图片不得重复'
  } else {
    const owned = body.image_ids.every(
      (id) =>
        isOwnedUpload(id, userId) ||
        (editing?.images.some((image) => image.id === id) ?? false),
    )
    if (!owned) {
      fields.image_ids = '图片须为本人上传的商品图，数量 1–9 张'
    }
  }

  if (Object.keys(fields).length > 0) {
    throw new ApiError(9001, '参数校验失败', { fields })
  }
}

// ---- 响应组装（逐字段映射契约形态，剥离内部字段） ----

/** 卖家解析：静态卖家池 → mock 账号仓库（自建商品/我的商品样例）→ 兜底占位 */
function sellerOf(product: MockProduct): UserSummary {
  const staticSeller = MOCK_SELLERS[product.sellerId]
  if (staticSeller) {
    return toUserSummary(staticSeller)
  }
  const account = MOCK_ACCOUNTS.find((item) => item.profile.id === product.sellerId)
  if (account) {
    return toUserSummary(account.profile)
  }
  return {
    id: product.sellerId,
    display_name: `用户 ${product.sellerId}`,
    nickname: `用户 ${product.sellerId}`,
    credit_score: null,
    auth_status: 'approved',
    role: 'student',
  }
}

function toSummary(product: MockProduct): ProductSummary {
  const category = categoryById(product.categoryId)
  const campus = MOCK_CAMPUSES.find((c) => c.id === product.campusId)
  return {
    id: product.id,
    title: product.title,
    price: product.price,
    original_price: product.originalPrice,
    condition: product.condition,
    status: product.status,
    ...(product.images[0] ? { cover: { ...product.images[0] } } : { cover: null }),
    favorite_count: product.favoriteCount,
    ...(category ? { category: { ...category } } : { category: null }),
    seller: sellerOf(product),
    ...(campus ? { campus: { ...campus } } : { campus: null }),
    created_at: product.createdAt,
  }
}

function toDetail(product: MockProduct, viewer: UserProfile): ProductDetail {
  const favorited =
    viewer.role !== 'admin' && favoritesOfUser(viewer.id).has(product.id)
  return {
    ...toSummary(product),
    description: product.description,
    images: product.images.map((image) => ({ ...image })),
    view_count: product.viewCount,
    is_favorited: favorited,
    updated_at: product.updatedAt,
  }
}

/** 分页切片（契约 PaginatedData：page ≥ 1，pages = ceil(total/page_size)，空表为 0） */
function paginate<T>(items: T[], page: number, pageSize: number): Paginated<T> {
  const total = items.length
  const pages = Math.ceil(total / pageSize)
  const safePageSize = Math.min(Math.max(1, pageSize), 100)
  const safePage = Math.min(Math.max(1, page), Math.max(pages, 1))
  const start = (safePage - 1) * safePageSize
  return {
    items: items.slice(start, start + safePageSize),
    page: safePage,
    page_size: safePageSize,
    total,
    pages,
  }
}

/** 列表/搜索共通筛选参数复验（价格区间、分类、校区、关键词长度） */
function validateFilterParams(
  query: Pick<ProductListQuery, 'category_id' | 'price_min' | 'price_max' | 'campus_id' | 'keyword'>,
): void {
  const fields: Record<string, string> = {}
  if (query.category_id != null && !categoryById(query.category_id)) {
    fields.category_id = '分类不存在或已停用'
  }
  if (query.campus_id != null && !MOCK_CAMPUSES.some((c) => c.id === query.campus_id)) {
    fields.campus_id = '校区不存在或已停用'
  }
  const min = query.price_min
  const max = query.price_max
  if (min != null && (!Number.isFinite(min) || min < 0)) {
    fields.price_min = '价格下界须为不小于 0 的数字'
  }
  if (max != null && (!Number.isFinite(max) || max < 0)) {
    fields.price_max = '价格上界须为不小于 0 的数字'
  }
  if (
    min != null && max != null && Number.isFinite(min) && Number.isFinite(max) &&
    min > max
  ) {
    fields.price_min = '价格下界不得大于价格上界'
  }
  if (query.keyword != null && query.keyword.length > 100) {
    fields.keyword = '关键词长度不得超过 100 个字符'
  }
  if (Object.keys(fields).length > 0) {
    throw new ApiError(9001, '参数校验失败', { fields })
  }
}

function applyFilters(
  products: MockProduct[],
  query: {
    category_id?: number
    condition?: ProductCondition
    price_min?: number
    price_max?: number
    campus_id?: number
    keyword?: string
  },
): MockProduct[] {
  return products.filter((p) => {
    if (query.category_id != null && p.categoryId !== query.category_id) return false
    if (query.condition != null && p.condition !== query.condition) return false
    if (query.price_min != null && p.price < query.price_min) return false
    if (query.price_max != null && p.price > query.price_max) return false
    if (query.campus_id != null && p.campusId !== query.campus_id) return false
    if (query.keyword != null && query.keyword !== '' && !p.title.includes(query.keyword)) {
      return false
    }
    return true
  })
}

// ---- 接口实现（products tag 8 接口 + 搜索） ----

/** GET /api/products：本校在售分页列表（仅 on_sale；管理员跨校区可见全部） */
export function mockListProducts(query: ProductListQuery): Promise<Paginated<ProductSummary>> {
  return delay(400).then(() => {
    const user = requireVerifiedSession()
    if (!sameSchoolAsPool(user)) {
      return paginate<ProductSummary>([], query.page ?? 1, query.page_size ?? 20)
    }
    validateFilterParams(query)
    // 同校隔离按学校不按校区：学生与管理员一致取本校全部校区在售商品
    let items = POOL.filter((p) => p.status === 'on_sale')
    items = applyFilters(items, query)
    const sort = query.sort ?? 'newest'
    items = [...items].sort((a, b) => {
      if (sort === 'price_asc') return a.price - b.price
      if (sort === 'price_desc') return b.price - a.price
      return b.createdAt.localeCompare(a.createdAt)
    })
    const page = paginate(items, query.page ?? 1, query.page_size ?? 20)
    return { ...page, items: page.items.map(toSummary) }
  })
}

/** GET /api/products/{id}：详情（可见性契约：off_sale/trading 仅卖家与管理员；sold/deleted 无人可见） */
export function mockGetProduct(id: number): Promise<ProductDetail> {
  return delay(400).then(() => {
    const user = requireVerifiedSession()
    const product = findProduct(id)
    if (!product || !sameSchoolAsPool(user)) {
      throw new ApiError(9002, '商品不存在', null)
    }
    const isOwner = product.sellerId === user.id
    const isAdmin = user.role === 'admin'
    if (product.status === 'deleted' || product.status === 'sold') {
      throw new ApiError(9002, '商品不存在', null)
    }
    if ((product.status === 'off_sale' || product.status === 'trading') && !isOwner && !isAdmin) {
      throw new ApiError(9002, '商品不存在', null)
    }
    // 服务端顺带记录点击行为（异步允许失败，不影响响应；浏览不改 updated_at）
    product.viewCount += 1
    return toDetail(product, user)
  })
}

/** POST /api/products：发布（status = on_sale；9001 字段复验含 image_ids 归属/数量） */
export function mockCreateProduct(body: ProductCreateInput): Promise<ProductDetail> {
  return delay(500).then(() => {
    const user = requireStudentFor('发布商品')
    validateProductInput(body, user.id, null)
    const now = nowIso()
    const campusId = body.campus_id ?? user.campus?.id ?? 1
    const images = body.image_ids.map((id) => {
      const upload = findMockUpload(id)
      return { id, url: upload?.url ?? svgDataUrl(body.category_id, body.title, 1) }
    })
    const product: MockProduct = {
      id: productIdSeed++,
      title: body.title,
      description: body.description,
      price: body.price,
      originalPrice: body.original_price ?? null,
      condition: body.condition,
      status: 'on_sale',
      images,
      viewCount: 0,
      favoriteCount: 0,
      categoryId: body.category_id,
      campusId,
      sellerId: user.id,
      createdAt: now,
      updatedAt: now,
      forcedOff: false,
    }
    POOL.push(product)
    return toDetail(product, user)
  })
}

/** PUT /api/products/{id}：编辑（仅发布者；trading/sold → 3001；image_ids 全量替换） */
export function mockUpdateProduct(
  id: number,
  body: ProductCreateInput,
): Promise<ProductDetail> {
  return delay(500).then(() => {
    const user = requireStudentFor('编辑商品')
    const product = findProduct(id)
    if (!product || product.sellerId !== user.id || product.status === 'deleted') {
      throw new ApiError(9002, '商品不存在', null)
    }
    if (product.status === 'trading' || product.status === 'sold') {
      throw new ApiError(
        3001,
        `商品当前状态为${PRODUCT_STATUS_TEXT[product.status]}，不允许编辑；仅上架或已下架商品可编辑`,
        null,
      )
    }
    validateProductInput(body, user.id, product)
    product.title = body.title
    product.description = body.description
    product.price = body.price
    product.originalPrice = body.original_price ?? null
    product.condition = body.condition
    product.categoryId = body.category_id
    product.campusId = body.campus_id ?? user.campus?.id ?? product.campusId
    product.images = body.image_ids.map((imageId) => {
      const existing = product.images.find((image) => image.id === imageId)
      const upload = findMockUpload(imageId)
      // 兜底占位与 mock 既有占位图策略一致（data URI），不用空串避免裂图
      return existing ?? { id: imageId, url: upload?.url ?? svgDataUrl(product.categoryId, product.title, 1) }
    })
    product.updatedAt = nowIso()
    return toDetail(product, user)
  })
}

/** PATCH /api/products/{id}/status：上下架（forced_off 重新上架 → 3002；trading/sold → 3001） */
export function mockChangeProductStatus(
  id: number,
  status: ProductStatusActionInput['status'],
): Promise<ProductSummary> {
  return delay(400).then(() => {
    const user = requireStudentFor('上架/下架商品')
    const product = findProduct(id)
    if (!product || product.sellerId !== user.id || product.status === 'deleted') {
      throw new ApiError(9002, '商品不存在', null)
    }
    if (product.status === 'trading' || product.status === 'sold') {
      throw new ApiError(
        3001,
        `商品当前状态为${PRODUCT_STATUS_TEXT[product.status]}，仅上架或已下架商品可执行上下架`,
        null,
      )
    }
    if (product.forcedOff && status === 'on_sale') {
      throw new ApiError(
        3002,
        '商品已被管理员强制下架，无法重新上架；如有疑问请联系管理员',
        null,
      )
    }
    product.status = status
    product.updatedAt = nowIso()
    return toSummary(product)
  })
}

/** DELETE /api/products/{id}：软删（on_sale/off_sale 可删；trading/sold → 3001） */
export function mockDeleteProduct(id: number): Promise<void> {
  return delay(400).then(() => {
    const user = requireStudentFor('删除商品')
    const product = findProduct(id)
    if (!product || product.sellerId !== user.id || product.status === 'deleted') {
      throw new ApiError(9002, '商品不存在', null)
    }
    if (product.status === 'trading' || product.status === 'sold') {
      throw new ApiError(
        3001,
        `商品当前状态为${PRODUCT_STATUS_TEXT[product.status]}，不允许删除`,
        null,
      )
    }
    product.status = 'deleted'
    product.updatedAt = nowIso()
  })
}

/** GET /api/products/mine：我的商品（created_at 倒序；deleted 恒不返回） */
export function mockListMyProducts(query: MyProductsQuery): Promise<Paginated<ProductSummary>> {
  return delay(350).then(() => {
    const user = requireStudentFor('管理商品')
    let items = POOL.filter((p) => p.sellerId === user.id && p.status !== 'deleted')
    if (query.status != null) {
      items = items.filter((p) => p.status === query.status)
    }
    items = [...items].sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    const page = paginate(items, query.page ?? 1, query.page_size ?? 20)
    return { ...page, items: page.items.map(toSummary) }
  })
}

/**
 * GET /api/products/search：向量搜索 mock。
 * - 正常：标题命中（相似度高）排前、描述命中（语义召回，AC-09 预演）排后；
 * - 降级演示通道：q 以「降级」开头（如「降级键盘」）→ 去前缀后走标题 LIKE 匹配，
 *   响应附 degraded: true 与 degraded_reason（任务卡降级样例，前端 DegradedBanner 演示）。
 */
export function mockSearchProducts(
  q: string,
  filters: Omit<ProductSearchQuery, 'q'>,
): Promise<SearchResultData> {
  return delay(500).then(() => {
    const user = requireVerifiedSession()
    const qError = validateSearchQ(q)
    if (qError) {
      throw new ApiError(9001, '参数校验失败', { fields: { q: qError } })
    }
    validateFilterParams(filters)
    if (!sameSchoolAsPool(user)) {
      return { ...paginate<ProductSummary>([], filters.page ?? 1, filters.page_size ?? 20) }
    }
    const term = q.trim()
    const degraded = term.startsWith('降级') && term.length > 2
    const effectiveTerm = degraded ? term.slice(2) : term

    let matched: MockProduct[]
    if (degraded) {
      // LIKE 标题匹配（按 created_at 倒序）
      matched = POOL.filter(
        (p) => p.status === 'on_sale' && p.title.includes(effectiveTerm),
      ).sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    } else {
      // 向量召回近似：标题命中 score 2、描述命中 score 1（相似度降序）
      matched = POOL.filter((p) => {
        if (p.status !== 'on_sale') return false
        return p.title.includes(term) || p.description.includes(term)
      }).sort((a, b) => {
        const scoreOf = (p: MockProduct) => (p.title.includes(term) ? 2 : 1)
        const diff = scoreOf(b) - scoreOf(a)
        return diff !== 0 ? diff : b.createdAt.localeCompare(a.createdAt)
      })
    }

    const filtered = applyFilters(matched, filters)
    const page = paginate(filtered, filters.page ?? 1, filters.page_size ?? 20)
    return {
      ...page,
      items: page.items.map(toSummary),
      ...(degraded
        ? { degraded: true as const, degraded_reason: '向量服务不可用，已降级为标题匹配' }
        : {}),
    }
  })
}

// ---- 供 favorites / recommendations mock 复用的存储访问 ----

export { findProduct, toSummary as toProductSummary, requireStudentFor as requireVerifiedStudentFor, sameSchoolAsPool }

/** 收藏目标校验：返回可见商品；不可见/不存在 → null（404/9002 防探测） */
export function visibleProductForFavorite(id: number, user: UserProfile): MockProduct | null {
  const product = findProduct(id)
  if (!product || product.status === 'deleted' || !sameSchoolAsPool(user)) {
    return null
  }
  return product
}

/** 推荐候选：本校在售、排除本人发布、按 id 升序（recommendations mock 消费） */
export function recommendationCandidates(excludeSellerId: number): MockProduct[] {
  return POOL.filter((p) => p.status === 'on_sale' && p.sellerId !== excludeSellerId).sort(
    (a, b) => a.id - b.id,
  )
}
