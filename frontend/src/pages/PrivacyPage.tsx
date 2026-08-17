/* Page-11 隐私政策（PIPL 合规基础页）
   正文结构来自设计规范；正式条款文字由 /项目负责人 提供，本页为结构占位 */
import BreadcrumbNav from '../components/ui/BreadcrumbNav';

const SECTIONS = [
  {
    title: '一、我们收集的信息',
    paragraphs: ['手机号、用户名等注册信息', '简历解析产生的结构化信息（教育背景、技能、经历等）', '职业分析报告与成长计划数据', '服务使用日志（不含简历原文件）'],
  },
  {
    title: '二、信息的使用',
    paragraphs: ['生成职业画像、方向推荐、差距分析与成长计划', '计划执行跟踪与进度同步', '服务改进与个性化体验优化'],
  },
  {
    title: '三、信息的存储与保护',
    paragraphs: ['账号密码加密存储（bcrypt 哈希）', '简历原文件解析后不长期保留', '传输与存储遵循安全规范（HTTPS / 数据隔离）'],
  },
  {
    title: '四、信息的共享',
    paragraphs: ['我们不会向第三方出售你的个人信息', '除法律法规要求外，不向第三方披露'],
  },
  {
    title: '五、你的权利',
    paragraphs: ['查阅、更正、删除你的个人信息', '撤回同意与注销账号的权利'],
  },
  {
    title: '六、联系方式',
    paragraphs: ['如有隐私相关问题，可通过应用内页面反馈联系我们'],
  },
];

export default function PrivacyPage() {
  return (
    <div className="container-read page-body">
      <BreadcrumbNav items={[{ label: '仪表盘', path: '/' }, { label: '隐私政策' }]} />

      <h1 style={{ fontSize: 'var(--font-size-2xl)', fontWeight: 600, margin: '0 0 var(--space-2)' }}>隐私政策</h1>
      <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)', marginBottom: 'var(--space-8)' }}>
        生效日期：2026-08-05 · 版本 v1.0
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
        {SECTIONS.map((section) => (
          <section key={section.title}>
            <h2 style={{ fontSize: 'var(--font-size-lg)', fontWeight: 600, margin: '0 0 var(--space-3)' }}>{section.title}</h2>
            <ul style={{ margin: 0, paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', fontSize: 'var(--font-size-sm)', lineHeight: 22, color: 'var(--color-text-secondary)' }}>
              {section.paragraphs.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      <div style={{ marginTop: 'var(--space-12)', fontSize: 'var(--font-size-xs)', color: 'var(--color-text-tertiary)' }}>
        正式条款文字由产品与法务提供最终稿后替换（当前为结构占位）。
      </div>
    </div>
  );
}
