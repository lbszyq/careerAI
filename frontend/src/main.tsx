/* ============================================================
   CareerAI 前端入口
   技术栈：React 18 + Ant Design 5 + Vite + TanStack Query v5 + ECharts 5
   ============================================================ */
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigProvider, App as AntApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import { AuthProvider } from './stores/AuthProvider';
import { LoginModalProvider } from './hooks/LoginModalProvider';
import './styles/tokens.css';
import './styles/global.css';

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          token: {
            colorPrimary: '#2C4A6E',
            colorInfo: '#3D6B99',
            colorSuccess: '#4E7A5B',
            colorWarning: '#B9762E',
            colorError: '#B24D3E',
            colorText: '#232A33',
            colorTextSecondary: '#4A5560',
            colorBgLayout: '#FAF7F2',
            colorBorder: '#E2DCD2',
            colorBorderSecondary: '#EDE7DE',
            borderRadius: 4,
            fontFamily: '"HarmonyOS Sans SC", "MiSans", "PingFang SC", "Microsoft YaHei", sans-serif',
            controlHeight: 40,
          },
          components: {
            Button: { primaryShadow: 'none', fontWeight: 600 },
          },
        }}
      >
        <AntApp>
          <AuthProvider>
            <LoginModalProvider>
              <BrowserRouter>
                <App />
              </BrowserRouter>
            </LoginModalProvider>
          </AuthProvider>
        </AntApp>
      </ConfigProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
