/* C-16 断网横幅 NetworkBanner：监听 navigator.onLine */
import { useEffect, useState } from 'react';
import { WifiOutlined } from '@ant-design/icons';

export default function NetworkBanner() {
  const [offline, setOffline] = useState(() => typeof navigator !== 'undefined' && !navigator.onLine);

  useEffect(() => {
    const handleOffline = () => setOffline(true);
    const handleOnline = () => setOffline(false);
    window.addEventListener('offline', handleOffline);
    window.addEventListener('online', handleOnline);
    return () => {
      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('online', handleOnline);
    };
  }, []);

  if (!offline) return null;

  return (
    <div
      role="alert"
      style={{
        height: 40,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        backgroundColor: 'var(--color-warning-600)',
        color: '#fff',
        fontSize: 'var(--font-size-sm)',
      }}
    >
      <WifiOutlined />
      网络连接异常，请检查网络
    </div>
  );
}
