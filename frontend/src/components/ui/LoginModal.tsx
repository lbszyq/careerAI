/* C-32 登录 Modal（page-10 内容）
    决策①：登录 = Modal 弹窗（非独立路由页）
   - 登录 / 注册 Tab，账号密码主流程（CR-001/）
   - 短信验证码 / 微信扫码入口 本地版本 隐藏（组件定义保留）
   - 阶段二：接入真实 API（auth-contract），JWT 由 AuthStore 持久化 */
import { Modal, Tabs, Form, Input, Button, Checkbox, Alert, App as AntApp } from 'antd';
import { UserOutlined, LockOutlined, MobileOutlined } from '@ant-design/icons';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../stores/useAuthStore';
import { useLoginModal } from '../../hooks/useLoginModal';
import { ApiClientError } from '../../services/http';
import { toUserMessage } from '../../services/errorMapping';

interface LoginFormValues {
  account: string;
  password: string;
}
interface RegisterFormValues {
  username: string;
  phone?: string;
  password: string;
  confirmPassword: string;
}

export default function LoginModal() {
  const { open, closeLogin } = useLoginModal();
  const { login, register } = useAuth();
  const { message } = AntApp.useApp();

  const [tab, setTab] = useState<'login' | 'register'>('login');
  const [agree, setAgree] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const handleLogin = async (values: LoginFormValues) => {
    if (!agree) {
      message.warning('请先同意用户协议与隐私政策');
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      await login({ account: values.account.trim(), password: values.password });
      message.success('登录成功');
      closeLogin();
    } catch (err) {
      if (err instanceof ApiClientError) {
        // 1001 统一文案「账号或密码错误」（后端已统一，防账号枚举）
        setFormError(err.code === 1001 ? '账号或密码错误' : toUserMessage(err));
      } else {
        setFormError('登录失败，请稍后重试');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleRegister = async (values: RegisterFormValues) => {
    if (!agree) {
      message.warning('请先同意用户协议与隐私政策');
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      const payload = {
        username: values.username.trim(),
        // 契约：phone 可选；后端对空字符串会校验失败，未填时省略字段
        ...(values.phone?.trim() ? { phone: values.phone.trim() } : {}),
        password: values.password,
      };
      await register(payload);
      message.success('注册成功，已自动登录');
      closeLogin();
    } catch (err) {
      if (err instanceof ApiClientError) {
        setFormError(toUserMessage(err));
      } else {
        setFormError('注册失败，请稍后重试');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleSubmit = () => {
    if (!agree) {
      message.warning('请先同意用户协议与隐私政策');
    }
  };

  return (
    <Modal
      open={open}
      onCancel={closeLogin}
      footer={null}
      width={400}
      centered
      destroyOnHidden
      title={null}
      styles={{ body: { padding: 'var(--space-6)' } }}
    >
      <div style={{ textAlign: 'center', marginBottom: 'var(--space-4)' }}>
        <div style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600, color: 'var(--color-text-primary)' }}>登录 CareerAI</div>
        <div style={{ marginTop: 4, fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>
          登录后生成报告并保存到你的账号
        </div>
        {tab === 'login' && (
          <div style={{ marginTop: 4, fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>
            还没有账号？<a onClick={() => setTab('register')}>切换到「注册」</a>
          </div>
        )}
      </div>

      <Tabs
        activeKey={tab}
        onChange={(key) => {
          setTab(key as 'login' | 'register');
          setFormError(null);
        }}
        centered
        items={[
          { key: 'login', label: '登录' },
          { key: 'register', label: '注册' },
        ]}
      />

      {formError && (
        <Alert type="error" showIcon message={formError} style={{ marginBottom: 'var(--space-4)', borderRadius: 'var(--radius-md)' }} />
      )}

      {tab === 'login' ? (
        <Form layout="vertical" onFinish={handleLogin} requiredMark={false}>
          <Form.Item
            name="account"
            label="账号"
            rules={[{ required: true, message: '请输入用户名或手机号' }, { max: 64, message: '账号最长 64 位' }]}
          >
            <Input prefix={<UserOutlined />} placeholder="用户名或手机号" size="large" autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="请输入密码" size="large" autoComplete="current-password" />
          </Form.Item>

          <Button type="primary" htmlType="submit" size="large" block loading={submitting} onClick={handleSubmit}>
            登录
          </Button>
        </Form>
      ) : (
        <Form layout="vertical" onFinish={handleRegister} requiredMark={false}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[
              { required: true, message: '请输入用户名' },
              { pattern: /^[\w\u4e00-\u9fa5]{3,64}$/, message: '用户名 3-64 位，仅字母/数字/下划线/中文' },
            ]}
          >
            <Input prefix={<UserOutlined />} placeholder="设置用户名（3-64 位）" size="large" autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="phone"
            label="手机号（可选）"
            rules={[{ pattern: /^1[3-9]\d{9}$/, message: '请输入正确的手机号' }]}
          >
            <Input prefix={<MobileOutlined />} placeholder="手机号（可选）" size="large" autoComplete="tel" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请设置密码' }, { min: 8, max: 128, message: '密码 8-128 位' }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="设置密码（至少 8 位）" size="large" autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirmPassword"
            label="确认密码"
            dependencies={['password']}
            rules={[
              { required: true, message: '请再次输入密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('password') === value) return Promise.resolve();
                  return Promise.reject(new Error('两次输入的密码不一致'));
                },
              }),
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="再次输入密码" size="large" autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" size="large" block loading={submitting} onClick={handleSubmit}>
            注册
          </Button>
        </Form>
      )}

      {/* 后置通道：短信验证码登录（V1.1 后置，本地版本 不渲染入口） / 微信扫码（未启用时隐藏） */}
      {/* TODO: 非本地版本 —— 短信验证码 / 微信扫码登录入口（V1.1 启用后按交互规范渲染） */}

      <div style={{ marginTop: 'var(--space-4)', textAlign: 'center' }}>
        <Checkbox checked={agree} onChange={(e) => setAgree(e.target.checked)}>
          <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-secondary)' }}>
            我已阅读并同意
            <Link to="/privacy" target="_blank" style={{ margin: '0 4px' }}>《用户协议》</Link>
            <Link to="/privacy" target="_blank">《隐私政策》</Link>
          </span>
        </Checkbox>
      </div>
    </Modal>
  );
}
