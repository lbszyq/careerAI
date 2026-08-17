/* ============================================================
   ProfilePage 画像表单转换 + 上传流程测试
   覆盖（任务标准 1 之③）：
   1) toUpsert / fromProfile 纯函数：字段映射、空值归一化、往返一致性
   2) 简历上传交互：非 PDF、超 10MB、未登录弹登录、登录后成功解析回填
   3) 保存并生成报告：未登录存草稿+弹登录、登录成功链路、必填校验拦截
   依赖注入：mock services/hooks，antd Upload 以假 Dragger 触发 beforeUpload
   ============================================================ */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ConfigProvider, App as AntApp } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ProfilePage, { fromProfile, toUpsert, type ProfileFormValues } from './ProfilePage';
import { ApiClientError } from '../services/http';
import type { ApiProfile } from '../types';

/* ---------- 可控 mock 状态（vi.hoisted 避免 vi.mock 提升陷阱） ---------- */
const mockState = vi.hoisted(() => ({
  isLoggedIn: false,
  uploadFile: null as File | null,
  openLogin: vi.fn(),
  navigate: vi.fn(),
  profileApi: { uploadResume: vi.fn(), get: vi.fn(), upsert: vi.fn() },
  reportsApi: { create: vi.fn(), list: vi.fn(), detail: vi.fn(), createGap: vi.fn(), regeneratePlan: vi.fn() },
  tasksApi: { get: vi.fn(), trigger: vi.fn(), cancel: vi.fn() },
}));

vi.mock('../services/profileApi', () => ({ profileApi: mockState.profileApi }));
vi.mock('../services/reportsApi', () => ({ reportsApi: mockState.reportsApi }));
vi.mock('../services/tasksApi', () => ({ tasksApi: mockState.tasksApi }));
vi.mock('../hooks/useLoginModal', () => ({
  useLoginModal: () => ({ open: false, openLogin: mockState.openLogin, closeLogin: vi.fn() }),
}));
vi.mock('../stores/useAuthStore', () => ({
  useAuth: () => ({
    isLoggedIn: mockState.isLoggedIn,
    user: null,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    refreshMe: vi.fn(),
    onAuthExpired: vi.fn(),
  }),
}));
vi.mock('react-router-dom', () => ({ useNavigate: () => mockState.navigate }));
// antd 仅替换 Upload.Dragger 为可控触发按钮（其余组件保持真实，便于断言 Alert/Form 行为）
vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal<typeof import('antd')>();
  const FakeDragger = (props: { beforeUpload?: (file: File) => unknown }) => (
    <button
      type="button"
      onClick={() => {
        if (mockState.uploadFile) props.beforeUpload?.(mockState.uploadFile);
      }}
    >
      上传简历（模拟）
    </button>
  );
  return { ...actual, Upload: Object.assign(actual.Upload, { Dragger: FakeDragger }) };
});

/* ---------- fixtures ---------- */

const profileFixture: ApiProfile = {
  id: 'p1',
  name: '张三',
  school: 'XX大学',
  major: '计算机',
  education: '本科',
  graduation_year: 2026,
  gpa: 3.5,
  skills: ['Python', 'SQL'],
  internships: [{ company: 'A公司', role: '前端实习生', duration: '2025-06 至 2025-09' }],
  projects: [{ name: '职业分析平台', description: '全栈项目', tech: ['React', 'FastAPI'] }],
  certificates: ['CET-6'],
  preferred_cities: ['北京'],
  preferred_industries: ['互联网'],
  expected_salary: 15000,
  is_active: true,
  created_at: '2026-08-14T10:00:00',
  updated_at: '2026-08-14T10:00:00',
};

function succeededTask() {
  return {
    id: 't1',
    task_type: 'resume_parse',
    status: 'succeeded',
    progress: 100,
    stage: null,
    result_ref: null,
    result: null,
    error_message: null,
    created_at: '2026-08-14T10:00:00',
    updated_at: '2026-08-14T10:00:00',
    finished_at: null,
  };
}

function renderPage() {
  return render(
    <ConfigProvider>
      <AntApp>
        <ProfilePage />
      </AntApp>
    </ConfigProvider>,
  );
}

const uploadButton = () => screen.getByRole('button', { name: '上传简历（模拟）' });

beforeEach(() => {
  mockState.isLoggedIn = false;
  mockState.uploadFile = null;
  mockState.openLogin.mockClear();
  mockState.navigate.mockClear();
  mockState.profileApi.uploadResume.mockReset();
  mockState.profileApi.get.mockReset();
  mockState.profileApi.upsert.mockReset();
  mockState.reportsApi.create.mockReset();
  mockState.tasksApi.get.mockReset();
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
});

/* ========== 1) toUpsert：表单 → 画像契约映射 ========== */
describe('toUpsert 表单→画像契约映射', () => {
  it('完整字段映射：学历/毕业年份转数字/期望薪资取中值/结构数组透传（正向）', () => {
    const values: ProfileFormValues = {
      name: '张三',
      school: 'XX大学',
      major: '计算机',
      degree: '本科',
      gradYear: '2026',
      gpa: 3.5,
      skills: ['Python', 'SQL'],
      certificates: ['CET-6'],
      internships: [{ company: 'A公司', role: '前端实习生', duration: '2025-06 至 2025-09' }],
      projects: [{ name: '职业分析平台', description: '全栈项目', tech: ['React'] }],
      cities: ['北京'],
      industries: ['互联网'],
      salaryRange: '12-18k',
    };

    expect(toUpsert(values)).toEqual({
      name: '张三',
      school: 'XX大学',
      major: '计算机',
      education: '本科',
      graduation_year: 2026,
      gpa: 3.5,
      skills: ['Python', 'SQL'],
      certificates: ['CET-6'],
      internships: [{ company: 'A公司', role: '前端实习生', duration: '2025-06 至 2025-09' }],
      projects: [{ name: '职业分析平台', description: '全栈项目', tech: ['React'] }],
      preferred_cities: ['北京'],
      preferred_industries: ['互联网'],
      expected_salary: 15000,
    });
  });

  it('空值归一化：缺省字段与空数组 → undefined（边界）', () => {
    expect(toUpsert({})).toEqual({
      name: undefined,
      school: undefined,
      major: undefined,
      education: undefined,
      graduation_year: undefined,
      gpa: undefined,
      skills: undefined,
      certificates: undefined,
      internships: undefined,
      projects: undefined,
      preferred_cities: undefined,
      preferred_industries: undefined,
      expected_salary: undefined,
    });

    expect(toUpsert({ certificates: [], internships: [], projects: [] }).certificates).toBeUndefined();
    expect(toUpsert({ certificates: [], internships: [], projects: [] }).internships).toBeUndefined();
    expect(toUpsert({ certificates: [], internships: [], projects: [] }).projects).toBeUndefined();
  });

  it('期望薪资映射：区间取中值 / 单值 k+ / 缺省 undefined', () => {
    expect(toUpsert({ salaryRange: '8-12k' }).expected_salary).toBe(10000);
    expect(toUpsert({ salaryRange: '25k+' }).expected_salary).toBe(25000);
    expect(toUpsert({ salaryRange: undefined }).expected_salary).toBeUndefined();
  });
});

/* ========== 2) fromProfile：画像契约 → 表单值 ========== */
describe('fromProfile 画像契约→表单值', () => {
  it('完整映射：毕业年份转字符串、期望薪资转最近区间（正向）', () => {
    expect(fromProfile(profileFixture)).toEqual({
      name: '张三',
      school: 'XX大学',
      major: '计算机',
      degree: '本科',
      gradYear: '2026',
      gpa: 3.5,
      skills: ['Python', 'SQL'],
      certificates: ['CET-6'],
      internships: [{ company: 'A公司', role: '前端实习生', duration: '2025-06 至 2025-09' }],
      projects: [{ name: '职业分析平台', description: '全栈项目', tech: ['React', 'FastAPI'] }],
      cities: ['北京'],
      industries: ['互联网'],
      salaryRange: '12-18k',
    });
  });

  it('空值兜底：null 字段 → undefined、空数组结构 → undefined（边界）', () => {
    const empty: ApiProfile = {
      id: 'p1',
      name: null,
      school: null,
      major: null,
      education: null,
      graduation_year: null,
      gpa: null,
      skills: [],
      internships: [],
      projects: [],
      certificates: [],
      preferred_cities: [],
      preferred_industries: [],
      expected_salary: null,
      is_active: true,
      created_at: '2026-08-14T10:00:00',
      updated_at: '2026-08-14T10:00:00',
    };

    expect(fromProfile(empty)).toEqual({
      name: undefined,
      school: undefined,
      major: undefined,
      degree: undefined,
      gradYear: undefined,
      gpa: undefined,
      skills: [],
      certificates: [],
      internships: undefined,
      projects: undefined,
      cities: [],
      industries: [],
      salaryRange: undefined,
    });
  });

  it('往返一致性：toUpsert(fromProfile(p)) 关键字段与原画像一致（边界）', () => {
    const roundTrip = toUpsert(fromProfile(profileFixture));

    expect(roundTrip.name).toBe('张三');
    expect(roundTrip.education).toBe('本科');
    expect(roundTrip.graduation_year).toBe(2026);
    expect(roundTrip.gpa).toBe(3.5);
    expect(roundTrip.skills).toEqual(['Python', 'SQL']);
    expect(roundTrip.certificates).toEqual(['CET-6']);
    expect(roundTrip.preferred_cities).toEqual(['北京']);
    expect(roundTrip.preferred_industries).toEqual(['互联网']);
    expect(roundTrip.internships).toEqual(profileFixture.internships);
    expect(roundTrip.projects).toEqual(profileFixture.projects);
    expect(roundTrip.expected_salary).toBe(15000);
  });
});

/* ========== 3) 简历上传交互 ========== */
describe('简历上传交互', () => {
  it('非 PDF 文件：展示错误提示，不发上传请求（异常）', async () => {
    mockState.uploadFile = new File(['x'], 'resume.png', { type: 'image/png' });
    renderPage();

    fireEvent.click(uploadButton());

    expect(await screen.findByText(/仅支持 PDF 文字版简历/)).toBeInTheDocument();
    expect(mockState.profileApi.uploadResume).not.toHaveBeenCalled();
  });

  it('超过 10MB：展示错误提示，不发上传请求（边界）', async () => {
    const bigFile = new File(['x'], 'big.pdf', { type: 'application/pdf' });
    Object.defineProperty(bigFile, 'size', { value: 11 * 1024 * 1024 });
    mockState.uploadFile = bigFile;
    renderPage();

    fireEvent.click(uploadButton());

    expect(await screen.findByText(/文件超过 10MB/)).toBeInTheDocument();
    expect(mockState.profileApi.uploadResume).not.toHaveBeenCalled();
  });

  it('未登录：弹出登录 Modal，不发上传请求', async () => {
    mockState.uploadFile = new File(['x'], 'resume.pdf', { type: 'application/pdf' });
    renderPage();

    fireEvent.click(uploadButton());

    expect(mockState.openLogin).toHaveBeenCalledTimes(1);
    expect(mockState.profileApi.uploadResume).not.toHaveBeenCalled();
  });

  it('登录 + PDF：上传→轮询任务→解析成功→回填画像并提示确认（正向）', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
    mockState.isLoggedIn = true;
    mockState.profileApi.uploadResume.mockResolvedValue({ task_id: 't1', status: 'pending' });
    mockState.tasksApi.get.mockResolvedValueOnce(succeededTask());
    mockState.profileApi.get.mockResolvedValue(profileFixture);
    mockState.uploadFile = new File(['x'], 'resume.pdf', { type: 'application/pdf' });

    renderPage();
    fireEvent.click(uploadButton());

    expect(mockState.profileApi.uploadResume).toHaveBeenCalledTimes(1);
    expect(mockState.profileApi.uploadResume).toHaveBeenCalledWith(expect.any(File));

    // 先冲刷微任务让 handleUpload 注册到 5s 定时器，再推进（一次性推进会跳过中间态）
    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });

    // 状态更新已在 act 内提交：用同步断言（globals:false 下 findBy* 的 waitFor 与 fake timers 死锁）
    expect(mockState.tasksApi.get).toHaveBeenCalledWith('t1');
    expect(mockState.profileApi.get).toHaveBeenCalled();
    expect(screen.getByText(/AI 识别结果，请确认/)).toBeInTheDocument();
    expect(screen.queryByText(/正在解析简历/)).not.toBeInTheDocument();
  });

  it('解析任务失败：展示失败提示（异常）', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
    mockState.isLoggedIn = true;
    mockState.profileApi.uploadResume.mockResolvedValue({ task_id: 't1', status: 'pending' });
    mockState.tasksApi.get.mockResolvedValueOnce({ ...succeededTask(), status: 'failed', error_message: '解析失败' });
    mockState.uploadFile = new File(['x'], 'resume.pdf', { type: 'application/pdf' });

    renderPage();
    fireEvent.click(uploadButton());

    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });

    expect(screen.getByText(/简历解析失败/)).toBeInTheDocument();
  });

  it('上传接口异常：展示映射后错误提示（异常）', async () => {
    mockState.isLoggedIn = true;
    mockState.profileApi.uploadResume.mockRejectedValue(new ApiClientError(3103, '仅支持 PDF 文字版简历', 400));
    mockState.uploadFile = new File(['x'], 'resume.pdf', { type: 'application/pdf' });

    renderPage();
    fireEvent.click(uploadButton());

    expect(await screen.findByText(/仅支持 PDF 文字版简历/)).toBeInTheDocument();
  });
});

/* ========== 4) 保存并生成报告 ========== */
describe('保存并生成报告', () => {
  async function fillRequiredFields() {
    fireEvent.change(screen.getByPlaceholderText('请输入姓名'), { target: { value: '张三' } });
    fireEvent.change(screen.getByPlaceholderText('请输入学校名称'), { target: { value: 'XX大学' } });
    fireEvent.change(screen.getByPlaceholderText('请输入专业'), { target: { value: '计算机' } });
  }

  it('未登录：保存会话草稿 + 弹登录，不发画像/报告请求', async () => {
    renderPage();
    await fillRequiredFields();

    fireEvent.click(screen.getByRole('button', { name: '保存并生成报告' }));

    await waitFor(() => expect(mockState.openLogin).toHaveBeenCalledTimes(1));
    expect(sessionStorage.getItem('careerai:pending_generate')).toBe('1');
    expect(localStorage.getItem('careerai:profile_draft')).not.toBeNull();
    expect(mockState.profileApi.upsert).not.toHaveBeenCalled();
    expect(mockState.reportsApi.create).not.toHaveBeenCalled();
    expect(mockState.navigate).not.toHaveBeenCalled();
  });

  it('登录：PUT 画像（toUpsert 映射）→ POST 报告 → 跳转生成中页（正向）', async () => {
    mockState.isLoggedIn = true;
    mockState.profileApi.upsert.mockResolvedValue(profileFixture);
    mockState.reportsApi.create.mockResolvedValue({ task_id: 't1', status: 'pending' });

    renderPage();
    await fillRequiredFields();

    fireEvent.click(screen.getByRole('button', { name: '保存并生成报告' }));

    await waitFor(() => expect(mockState.profileApi.upsert).toHaveBeenCalledTimes(1));
    expect(mockState.profileApi.upsert).toHaveBeenCalledWith(
      expect.objectContaining({ name: '张三', school: 'XX大学', major: '计算机', education: undefined }),
    );
    expect(mockState.reportsApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ profile_id: 'p1', preferred_cities: undefined, preferred_industries: undefined }),
    );
    expect(mockState.navigate).toHaveBeenCalledWith('/generating?task_id=t1&stage=1');
    expect(mockState.openLogin).not.toHaveBeenCalled();
  });

  it('必填缺失：表单校验拦截，提示完善信息、不发任何请求（异常）', async () => {
    mockState.isLoggedIn = true;
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: '保存并生成报告' }));

    expect(await screen.findByText('请先完善必填信息（姓名/学校/专业）')).toBeInTheDocument();
    expect(mockState.profileApi.upsert).not.toHaveBeenCalled();
    expect(mockState.reportsApi.create).not.toHaveBeenCalled();
    expect(mockState.navigate).not.toHaveBeenCalled();
  });
});
