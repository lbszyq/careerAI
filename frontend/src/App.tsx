/* 应用路由与全局布局
   阶段一：TopNav + Footer 常驻；NetworkBanner 全局；LoginModal 全局弹窗（决策①）
   阶段二：全局 ErrorBoundary（非白屏）；登录态失效（401/1003）自动弹登录 Modal */
import { Component, Suspense, lazy, useEffect, type ReactNode } from 'react';
import { Routes, Route } from 'react-router-dom';
import { Layout, Button, Result, Spin } from 'antd';
import TopNav from './components/ui/TopNav';
import Footer from './components/ui/Footer';
import NetworkBanner from './components/ui/NetworkBanner';
import { useAuth } from './stores/useAuthStore';
import { useLoginModal } from './hooks/useLoginModal';

/* 路由级代码分割（性能优化）：页面按需加载，首屏仅拉取当前路由 chunk */
const HomePage = lazy(() => import('./pages/HomePage'));
const ProfilePage = lazy(() => import('./pages/ProfilePage'));
const GeneratingPage = lazy(() => import('./pages/GeneratingPage'));
const PortraitReportPage = lazy(() => import('./pages/report/PortraitReportPage'));
const DirectionsReportPage = lazy(() => import('./pages/report/DirectionsReportPage'));
const GapPlanReportPage = lazy(() => import('./pages/report/GapPlanReportPage'));
const ReportDetailPage = lazy(() => import('./pages/report/ReportDetailPage'));
const MyPlanPage = lazy(() => import('./pages/MyPlanPage'));
const MyReportsPage = lazy(() => import('./pages/MyReportsPage'));
const PrivacyPage = lazy(() => import('./pages/PrivacyPage'));
/** 登录 Modal：弹窗组件，非首屏必需，懒加载避免 antd Modal/Form 等进入首屏 chunk */
const LoginModal = lazy(() => import('./components/ui/LoginModal'));
/** 全局错误边界：渲染异常时不白屏，提供重载出口 */
class ErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  render() {
    if (this.state.hasError) {
      return (
        <Result
          status="error"
          title="页面出现异常"
          subTitle="请刷新页面重试；如果问题持续，请联系我们"
          extra={
            <Button type="primary" onClick={() => window.location.reload()}>
              刷新页面
            </Button>
          }
        />
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const { onAuthExpired } = useAuth();
  const { open, openLogin } = useLoginModal();

  // 登录态失效（401/1003）：自动弹登录 Modal（auth-contract 约束：清除本地 token 并跳转登录）
  useEffect(() => onAuthExpired(() => openLogin()), [onAuthExpired, openLogin]);

  return (
    <ErrorBoundary>
      <Layout style={{ minHeight: '100vh', background: 'var(--color-bg-canvas)' }}>
        <NetworkBanner />
        <TopNav />
        <Layout.Content>
          <Suspense
            fallback={
              <div
                role="status"
                aria-label="页面加载中"
                style={{ display: 'flex', justifyContent: 'center', alignItems: 'flex-start', padding: 48, minHeight: 360 }}
              >
                <Spin size="large" />
              </div>
            }
          >
            <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/generating" element={<GeneratingPage />} />
            <Route path="/report/portrait" element={<PortraitReportPage />} />
            <Route path="/report/directions" element={<DirectionsReportPage />} />
            <Route path="/report/gap-plan" element={<GapPlanReportPage />} />
            <Route path="/report/detail" element={<ReportDetailPage />} />
            <Route path="/my-plan" element={<MyPlanPage />} />
            <Route path="/my-reports" element={<MyReportsPage />} />
            <Route path="/privacy" element={<PrivacyPage />} />
            {/* 未知路由回首页 */}
              <Route path="*" element={<HomePage />} />
            </Routes>
          </Suspense>
        </Layout.Content>
        <Footer />
        {/* 登录弹窗：打开时才懒加载渲染，Suspense 兜底 */}
        {open && (
          <Suspense fallback={null}>
            <LoginModal />
          </Suspense>
        )}
      </Layout>
    </ErrorBoundary>
  );
}
