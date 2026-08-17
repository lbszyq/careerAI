/* C-10 页脚 Footer：© 2026 CareerAI + 隐私政策链接 */
import { Layout } from 'antd';
import { Link } from 'react-router-dom';

export default function Footer() {
  return (
    <Layout.Footer
      className="app-footer"
      style={{
        height: 64,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 'var(--space-6)',
        background: 'var(--color-bg-subtle)',
        color: 'var(--color-text-secondary)',
        fontSize: 'var(--font-size-sm)',
        padding: '0 var(--space-6)',
      }}
    >
      <span>© 2026 CareerAI</span>
      <Link to="/privacy" style={{ color: 'var(--color-text-secondary)' }}>
        隐私政策
      </Link>
    </Layout.Footer>
  );
}
