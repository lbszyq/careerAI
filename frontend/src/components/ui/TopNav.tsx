/* C-07 顶部导航 TopNav：通栏 64px；品牌 + 3 导航 + 用户区；
   未登录点击「我的计划/我的报告」→ 跳转对应页显示空状态 + 登录引导（不弹强制登录） */
import { Layout, Menu, Dropdown, Avatar, Button, Drawer } from 'antd';
import {
  AppstoreOutlined,
  CheckSquareOutlined,
  FileTextOutlined,
  MenuOutlined,
  UserOutlined,
  LogoutOutlined,
} from '@ant-design/icons';
import { Link, useLocation } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useAuth } from '../../stores/useAuthStore';
import { useLoginModal } from '../../hooks/useLoginModal';

const NAV_ITEMS = [
  { key: '/', label: '仪表盘', icon: <AppstoreOutlined /> },
  { key: '/my-plan', label: '我的计划', icon: <CheckSquareOutlined /> },
  { key: '/my-reports', label: '我的报告', icon: <FileTextOutlined /> },
];

export default function TopNav() {
  const location = useLocation();
  const { isLoggedIn, user, logout } = useAuth();
  const { openLogin } = useLoginModal();
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  const selectedKey = NAV_ITEMS.find((item) => location.pathname === item.key || location.pathname.startsWith(`${item.key}/`))?.key;

  const menuItems = NAV_ITEMS.map((item) => ({
    key: item.key,
    icon: item.icon,
    label: <Link to={item.key}>{item.label}</Link>,
  }));

  const userMenu = {
    items: [
      { key: 'profile', icon: <UserOutlined />, label: <Link to="/profile">我的资料</Link> },
      { type: 'divider' as const },
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: '退出登录',
        onClick: () => {
          logout();
        },
      },
    ],
  };

  return (
    <>
      <Layout.Header
        className="topnav"
        style={{
          height: 64,
          lineHeight: '64px',
          padding: '0 var(--space-6)',
          background: 'var(--color-bg-surface)',
          borderBottom: '1px solid var(--color-divider)',
          position: 'sticky',
          top: 0,
          zIndex: 100,
        }}
      >
        <div className="container-max" style={{ display: 'flex', alignItems: 'center', height: '100%', padding: 0, gap: 'var(--space-8)' }}>
          <Link to="/" style={{ fontSize: 'var(--font-size-lg)', fontWeight: 700, color: 'var(--color-primary-600)', whiteSpace: 'nowrap' }}>
            CareerAI
          </Link>

          {/* 桌面导航 */}
          <Menu
            mode="horizontal"
            selectedKeys={selectedKey ? [selectedKey] : []}
            items={menuItems}
            className="topnav-menu"
            style={{ flex: 1, borderBottom: 'none', background: 'transparent', minWidth: 0 }}
          />

          {/* 用户区 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', whiteSpace: 'nowrap' }}>
            {isLoggedIn ? (
              <Dropdown menu={userMenu} placement="bottomRight">
                <button
                  type="button"
                  aria-label="用户菜单"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    padding: '8px 4px',
                    minHeight: 44,
                    color: 'var(--color-text-primary)',
                    fontSize: 'var(--font-size-sm)',
                  }}
                >
                  <Avatar size={32} style={{ backgroundColor: 'var(--color-primary-100)', color: 'var(--color-primary-600)' }} icon={<UserOutlined />} />
                  {user?.username ?? '同学'}
                </button>
              </Dropdown>
            ) : (
              <Button type="primary" onClick={openLogin}>
                登录
              </Button>
            )}
            {/* 移动端汉堡 */}
            <Button
              type="text"
              aria-label="打开导航菜单"
              icon={<MenuOutlined />}
              onClick={() => setDrawerOpen(true)}
              style={{ display: 'none', minWidth: 44, minHeight: 44 }}
              className="mobile-menu-btn"
            />
          </div>
        </div>
      </Layout.Header>

      {/* 移动端抽屉 */}
      <Drawer
        title="CareerAI"
        placement="right"
        width={280}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        styles={{ body: { padding: 0 } }}
      >
        <Menu
          mode="inline"
          selectedKeys={selectedKey ? [selectedKey] : []}
          items={menuItems}
          style={{ borderInlineEnd: 'none' }}
          onClick={() => setDrawerOpen(false)}
        />
        <div style={{ padding: 'var(--space-4)' }}>
          {isLoggedIn ? (
            <Button block onClick={() => { logout(); setDrawerOpen(false); }}>退出登录</Button>
          ) : (
            <Button type="primary" block onClick={() => { setDrawerOpen(false); openLogin(); }}>
              登录
            </Button>
          )}
        </div>
      </Drawer>
    </>
  );
}
