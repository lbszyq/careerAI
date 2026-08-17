/* Page-02 个人信息
   - 简历上传（真实 API：POST /profile/resume → 轮询任务 → 回填；后端未就绪时引导手动填写）
   - 手动补填折叠面板（基本信息 / 技能 / 经历 / 偏好）
   - 会话草稿：未登录填写存 draftStore（表单不丢失），登录后 PUT /profile 自动落库
   - 「保存并生成报告」：未登录先弹登录 Modal；登录后 PUT /profile → POST /reports → 进入生成中 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Upload, Form, Input, Select, Collapse, Alert, Divider, App as AntApp } from 'antd';
import { InboxOutlined, PlusOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../stores/useAuthStore';
import { useLoginModal } from '../hooks/useLoginModal';
import { profileApi } from '../services/profileApi';
import { reportsApi } from '../services/reportsApi';
import { tasksApi } from '../services/tasksApi';
import { ApiClientError } from '../services/http';
import { toUserMessage } from '../services/errorMapping';
import { draftStore } from '../services/tokenStore';
import { cityOptions, industryOptions, degreeOptions, gradYearOptions, salaryRangeOptions, skillOptions } from '../services/mockData';
import type { ApiInternship, ApiProfile, ApiProfileUpsert, ApiProject } from '../types';

const { Dragger } = Upload;
const { TextArea } = Input;

const PENDING_GENERATE_KEY = 'careerai:pending_generate';
const ACTIVE_TASK_KEY = 'careerai:active_task';

/** 画像表单值（：为单测导出，不改语义） */
export interface ProfileFormValues {
  name?: string;
  school?: string;
  major?: string;
  degree?: string;
  gradYear?: string;
  gpa?: number;
  skills?: string[];
  certificates?: string[];
  internships?: ApiInternship[];
  projects?: ApiProject[];
  cities?: string[];
  industries?: string[];
  salaryRange?: string;
}

/** 薪资范围（如 '12-18k'）→ 中值（元/月） */
function salaryRangeToInt(range?: string): number | undefined {
  if (!range) return undefined;
  const match = range.match(/(\d+)\s*-\s*(\d+)/);
  if (match) return Math.round((Number(match[1]) + Number(match[2])) / 2) * 1000;
  const single = range.match(/^(\d+)k\+?$/);
  if (single) return Number(single[1]) * 1000;
  return undefined;
}

/** 期望薪资（元/月）→ 最近的范围选项 */
function salaryIntToRange(salary?: number | null): string | undefined {
  if (!salary) return undefined;
  const k = salary / 1000;
  const best = [...salaryRangeOptions].sort((a, b) => Math.abs(parseInt(a, 10) - k) - Math.abs(parseInt(b, 10) - k))[0];
  return best;
}

// eslint-disable-next-line react-refresh/only-export-components -- 可测性最小导出（任务允许），不改语义
export function toUpsert(values: ProfileFormValues): ApiProfileUpsert {
  return {
    name: values.name,
    school: values.school,
    major: values.major,
    education: values.degree,
    graduation_year: values.gradYear ? Number(values.gradYear) : undefined,
    gpa: values.gpa,
    skills: values.skills,
    certificates: values.certificates?.length ? values.certificates : undefined,
    // 契约 internships/projects 为结构化数组：逐条直传（/Q2）
    internships: values.internships?.length ? values.internships : undefined,
    projects: values.projects?.length ? values.projects : undefined,
    preferred_cities: values.cities,
    preferred_industries: values.industries,
    expected_salary: salaryRangeToInt(values.salaryRange),
  };
}

// eslint-disable-next-line react-refresh/only-export-components -- 可测性最小导出（任务允许），不改语义
export function fromProfile(p: ApiProfile): ProfileFormValues {
  return {
    name: p.name ?? undefined,
    school: p.school ?? undefined,
    major: p.major ?? undefined,
    degree: p.education ?? undefined,
    gradYear: p.graduation_year ? String(p.graduation_year) : undefined,
    gpa: p.gpa ?? undefined,
    skills: p.skills,
    certificates: p.certificates,
    internships: p.internships?.length ? p.internships : undefined,
    projects: p.projects?.length ? p.projects : undefined,
    cities: p.preferred_cities,
    industries: p.preferred_industries,
    salaryRange: salaryIntToRange(p.expected_salary),
  };
}

export default function ProfilePage() {
  const navigate = useNavigate();
  const { isLoggedIn } = useAuth();
  const { openLogin } = useLoginModal();
  const { message } = AntApp.useApp();
  const [form] = Form.useForm<ProfileFormValues>();
  const [parsing, setParsing] = useState(false);
  const [aiParsed, setAiParsed] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [profileLoaded, setProfileLoaded] = useState(false);
  const generationStartedRef = useRef(false);
  const isLoggedInRef = useRef(isLoggedIn);
  isLoggedInRef.current = isLoggedIn;

  // 登录后加载服务端画像回填（有画像且表单未加载过）
  useEffect(() => {
    if (!isLoggedIn || profileLoaded) return;
    let cancelled = false;
    (async () => {
      try {
        const profile = await profileApi.get();
        if (cancelled || !profile) return;
        // 表单已有用户输入时不覆盖
        const current = form.getFieldsValue();
        const hasInput = Object.values(current).some((v) => (Array.isArray(v) ? v.length > 0 : Boolean(v)));
        if (!hasInput) form.setFieldsValue(fromProfile(profile));
      } catch {
        /* 后端未就绪时静默，保持手动填写可用 */
      } finally {
        if (!cancelled) setProfileLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isLoggedIn, profileLoaded, form]);

  // 登录成功后：若用户是在本页触发的「保存并生成报告」，自动落库并进入生成流程
  useEffect(() => {
    if (!isLoggedIn) return;
    if (sessionStorage.getItem(PENDING_GENERATE_KEY) === '1') {
      sessionStorage.removeItem(PENDING_GENERATE_KEY);
      void handleGenerate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoggedIn]);

  // 简历上传：真实 API（异步解析任务）
  const handleUpload = async (file: File) => {
    setParseError(null);
    // 前端预检（契约：仅 PDF 文字版 ≤10MB；图片/扫描件 OCR V1.1 后置）
    if (!/\.pdf$/i.test(file.name)) {
      setParseError('仅支持 PDF 文字版简历（图片/扫描件暂不支持解析，OCR 后续版本支持），可手动填写下方表单');
      return false;
    }
    if (file.size > 10 * 1024 * 1024) {
      setParseError('文件超过 10MB：请压缩为 PDF 后重试（勿转成图片，图片版无法解析）；或直接手动填写下方表单');
      return false;
    }
    // 未登录：先弹登录 Modal（对齐 handleGenerate），不发请求；登录后重新点击上传即可
    if (!isLoggedInRef.current) {
      openLogin();
      return false;
    }
    setParsing(true);
    try {
      const accepted = await profileApi.uploadResume(file);
      // 轮询解析任务（5s；最多 12 次 = 60s）
      for (let i = 0; i < 12; i += 1) {
        await new Promise((r) => setTimeout(r, 5000));
        const job = await tasksApi.get(accepted.task_id);
        if (job.status === 'succeeded') {
          const profile = await profileApi.get();
          if (profile) {
            form.setFieldsValue(fromProfile(profile));
            setAiParsed(true);
            message.success('简历解析完成，请确认识别结果');
          }
          return false;
        }
        if (job.status === 'failed') {
          setParseError('简历解析失败，请手动填写或重试');
          return false;
        }
        if (job.status === 'cancelled') {
          return false;
        }
      }
      setParseError('简历解析时间较长，可先手动填写');
    } catch (err) {
      const msg = err instanceof ApiClientError ? toUserMessage(err) : '简历解析暂不可用';
      setParseError(msg === '该功能正在建设中，请稍后再试' ? '简历解析功能建设中，请手动填写' : msg);
    } finally {
      setParsing(false);
    }
    return false;
  };

  // 保存并生成报告
  const handleGenerate = useCallback(async () => {
    if (generationStartedRef.current) return;
    generationStartedRef.current = true;
    try {
      const values = await form.validateFields();
      setGenerating(true);

      // 未登录：会话草稿 + 弹登录（登录成功后自动继续）
      if (!isLoggedInRef.current) {
        draftStore.save(values as unknown as Record<string, unknown>);
        sessionStorage.setItem(PENDING_GENERATE_KEY, '1');
        openLogin();
        return;
      }

      // 1) 画像落库（登录后表单数据不丢失：PUT /profile）
      const profile = await profileApi.upsert(toUpsert(values));

      // 2) 提交 Stage 1 报告生成
      const accepted = await reportsApi.create({
        profile_id: profile.id,
        preferred_cities: values.cities,
        preferred_industries: values.industries,
      });

      // 3) 存任务 id（离开恢复用）→ 进入生成中页
      sessionStorage.setItem(ACTIVE_TASK_KEY, accepted.task_id);
      navigate(`/generating?task_id=${accepted.task_id}&stage=1`);
    } catch (err) {
      if (err instanceof ApiClientError) {
        message.error(toUserMessage(err));
      } else if (err && typeof err === 'object' && 'errorFields' in err) {
        message.warning('请先完善必填信息（姓名/学校/专业）');
      } else {
        message.error('提交失败，请稍后重试');
      }
    } finally {
      generationStartedRef.current = false;
      setGenerating(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form, navigate, openLogin]);

  // 保存草稿：本地持久化（draftStore），登录后自动同步到账号
  const handleSaveDraft = () => {
    const values = form.getFieldsValue();
    draftStore.save(values as unknown as Record<string, unknown>);
    message.success('草稿已保存到本地，登录后自动同步到账号');
  };

  return (
    <div className="container-read page-body">
      <h1 style={{ fontSize: 'var(--font-size-2xl)', fontWeight: 600, margin: '0 0 var(--space-2)' }}>完善你的职业信息</h1>
      <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)', marginBottom: 'var(--space-6)' }}>
        共 2 步，第 1 步：导入信息 · 生成报告前需登录
      </div>

      {!isLoggedIn && (
        <Alert
          type="info"
          showIcon
          message="当前填写内容将在本次会话保留，登录后自动同步到你的账号"
          style={{ marginBottom: 'var(--space-6)', borderRadius: 'var(--radius-md)' }}
        />
      )}

      <Form<ProfileFormValues> form={form} layout="vertical" requiredMark={false}>
        {/* ① 简历上传 */}
        <section aria-label="简历上传" style={{ marginBottom: 'var(--space-8)' }}>
          <h2 style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600 }}>① 上传简历（可选）</h2>
          <Dragger
            accept=".pdf"
            maxCount={1}
            beforeUpload={handleUpload}
            showUploadList={false}
            style={{ height: 160, borderRadius: 'var(--radius-md)', borderColor: 'var(--color-border-strong)', background: 'var(--color-bg-surface)' }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">拖拽简历到这里，或点击上传</p>
            <p className="ant-upload-hint">支持 PDF 文字版（≤ 10MB），AI 自动识别 10 类信息；图片/扫描件暂不支持解析，请手动填写下方表单（OCR 后续版本支持）</p>
          </Dragger>
          {parsing && (
            <Alert
              type="info"
              showIcon
              message="正在解析简历…"
              style={{ marginTop: 'var(--space-3)', borderRadius: 'var(--radius-md)' }}
            />
          )}
          {aiParsed && (
            <Alert
              type="info"
              showIcon
              message="AI 识别结果，请确认"
              description="识别字段已自动填充并高亮，可手动修改"
              style={{ marginTop: 'var(--space-3)', borderRadius: 'var(--radius-md)' }}
            />
          )}
          {parseError && (
            <Alert
              type="error"
              showIcon
              message={parseError}
              style={{ marginTop: 'var(--space-3)', borderRadius: 'var(--radius-md)' }}
            />
          )}
        </section>

        {/* ② 手动补填 */}
        <section aria-label="手动补填信息">
          <h2 style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600 }}>② 补充你的信息</h2>
          <Collapse
            defaultActiveKey={['basic']}
            expandIconPosition="end"
            items={[
              {
                key: 'basic', forceRender: true,
                label: '基本信息',
                children: (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                    <Form.Item name="name" label={<span>姓名 <span style={{ color: 'var(--color-danger-600)' }}>*</span></span>} rules={[{ required: true, message: '请输入姓名' }]}>
                      <Input placeholder="请输入姓名" style={aiParsed ? highlightedStyle : undefined} />
                    </Form.Item>
                    <Form.Item name="school" label={<span>学校 <span style={{ color: 'var(--color-danger-600)' }}>*</span></span>} rules={[{ required: true, message: '请输入学校' }]}>
                      <Input placeholder="请输入学校名称" style={aiParsed ? highlightedStyle : undefined} />
                    </Form.Item>
                    <Form.Item name="major" label={<span>专业 <span style={{ color: 'var(--color-danger-600)' }}>*</span></span>} rules={[{ required: true, message: '请输入专业' }]}>
                      <Input placeholder="请输入专业" style={aiParsed ? highlightedStyle : undefined} />
                    </Form.Item>
                    <div style={{ display: 'flex', gap: 'var(--space-4)' }}>
                      <Form.Item name="degree" label="学历" style={{ flex: 1 }}>
                        <Select placeholder="请选择学历" options={degreeOptions.map((d) => ({ label: d, value: d }))} style={aiParsed ? highlightedStyle : undefined} />
                      </Form.Item>
                      <Form.Item name="gradYear" label="毕业年份" style={{ flex: 1 }}>
                        <Select placeholder="请选择毕业年份" options={gradYearOptions.map((d) => ({ label: d, value: d }))} style={aiParsed ? highlightedStyle : undefined} />
                      </Form.Item>
                    </div>
                    <Form.Item name="gpa" label="GPA（0-4.0）" style={{ maxWidth: 240 }}>
                      <Input placeholder="如 3.5" type="number" min={0} max={4} step={0.01} />
                    </Form.Item>
                  </div>
                ),
              },
              {
                key: 'skills', forceRender: true,
                label: '技能与证书',
                children: (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                    <Form.Item name="skills" label="核心技能（支持搜索与自定义输入，回车添加）" style={{ marginBottom: 0 }}>
                      <Select mode="tags" placeholder="输入或搜索技能，回车添加" options={skillOptions.map((s) => ({ label: s, value: s }))} tokenSeparators={[',']} maxCount={20} style={aiParsed ? highlightedStyle : undefined} />
                    </Form.Item>
                    <Form.Item name="certificates" label="证书（如 CET-6、软考中级，回车添加）" style={{ marginBottom: 0 }}>
                      <Select mode="tags" placeholder="输入证书名称，回车添加" tokenSeparators={[',']} maxCount={20} style={aiParsed ? highlightedStyle : undefined} />
                    </Form.Item>
                  </div>
                ),
              },
              {
                key: 'experience', forceRender: true,
                label: '实习与项目经历',
                children: (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                    <div>
                      <div style={{ marginBottom: 'var(--space-2)', fontSize: 'var(--font-size-sm)', fontWeight: 600 }}>
                        实习经历（逐条添加 / 删除 / 编辑，AI 解析结果逐条回填）
                      </div>
                      <Form.List name="internships">
                        {(fields, { add, remove }) => (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                            {fields.map((field) => (
                              <div
                                key={field.key}
                                style={{
                                  border: '1px solid var(--color-border-default)',
                                  borderRadius: 'var(--radius-md)',
                                  padding: 'var(--space-3) var(--space-4)',
                                }}
                              >
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                  <span style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600 }}>实习经历 {field.name + 1}</span>
                                  <Button type="text" danger size="small" onClick={() => remove(field.name)} aria-label={`删除实习经历 ${field.name + 1}`}>
                                    删除
                                  </Button>
                                </div>
                                <Form.Item name={[field.name, 'company']} label={<span>公司名称 <span style={{ color: 'var(--color-danger-600)' }}>*</span></span>} rules={[{ required: true, message: '请输入公司名称' }]} style={{ marginTop: 'var(--space-2)' }}>
                                  <Input placeholder="请输入公司名称" style={aiParsed ? highlightedStyle : undefined} />
                                </Form.Item>
                                <div style={{ display: 'flex', gap: 'var(--space-4)' }}>
                                  <Form.Item name={[field.name, 'role']} label="岗位" style={{ flex: 1 }}>
                                    <Input placeholder="如 数据分析实习生" />
                                  </Form.Item>
                                  <Form.Item name={[field.name, 'duration']} label="时间段" style={{ flex: 1 }}>
                                    <Input placeholder="如 2025-06 至 2025-09" />
                                  </Form.Item>
                                </div>
                              </div>
                            ))}
                            <Button type="dashed" onClick={() => add()} icon={<PlusOutlined />} block>
                              添加实习经历
                            </Button>
                          </div>
                        )}
                      </Form.List>
                    </div>

                    <div>
                      <div style={{ marginBottom: 'var(--space-2)', fontSize: 'var(--font-size-sm)', fontWeight: 600 }}>
                        项目经历（逐条添加 / 删除 / 编辑，AI 解析结果逐条回填）
                      </div>
                      <Form.List name="projects">
                        {(fields, { add, remove }) => (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                            {fields.map((field) => (
                              <div
                                key={field.key}
                                style={{
                                  border: '1px solid var(--color-border-default)',
                                  borderRadius: 'var(--radius-md)',
                                  padding: 'var(--space-3) var(--space-4)',
                                }}
                              >
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                  <span style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600 }}>项目经历 {field.name + 1}</span>
                                  <Button type="text" danger size="small" onClick={() => remove(field.name)} aria-label={`删除项目经历 ${field.name + 1}`}>
                                    删除
                                  </Button>
                                </div>
                                <Form.Item name={[field.name, 'name']} label={<span>项目名称 <span style={{ color: 'var(--color-danger-600)' }}>*</span></span>} rules={[{ required: true, message: '请输入项目名称' }]} style={{ marginTop: 'var(--space-2)' }}>
                                  <Input placeholder="请输入项目名称" style={aiParsed ? highlightedStyle : undefined} />
                                </Form.Item>
                                <Form.Item name={[field.name, 'description']} label="项目描述">
                                  <TextArea rows={3} placeholder="描述项目背景、你的职责与结果…" showCount maxLength={300} />
                                </Form.Item>
                                <Form.Item name={[field.name, 'tech']} label="技术栈（可选）">
                                  <Select mode="tags" placeholder="输入技术栈，回车添加" tokenSeparators={[',']} />
                                </Form.Item>
                              </div>
                            ))}
                            <Button type="dashed" onClick={() => add()} icon={<PlusOutlined />} block>
                              添加项目经历
                            </Button>
                          </div>
                        )}
                      </Form.List>
                    </div>
                  </div>
                ),
              },
              {
                key: 'preference', forceRender: true,
                label: '求职偏好',
                children: (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                    <Form.Item name="cities" label="意向城市（最多 5 个）">
                      <Select mode="multiple" placeholder="请选择意向城市" options={cityOptions.map((c) => ({ label: c, value: c }))} maxCount={5} />
                    </Form.Item>
                    <Form.Item name="industries" label="意向行业（最多 5 个）">
                      <Select mode="multiple" placeholder="请选择意向行业" options={industryOptions.map((i) => ({ label: i, value: i }))} maxCount={5} />
                    </Form.Item>
                    <Form.Item name="salaryRange" label="期望薪资范围">
                      <Select placeholder="请选择期望薪资范围" options={salaryRangeOptions.map((s) => ({ label: s, value: s }))} />
                    </Form.Item>
                  </div>
                ),
              },
            ]}
          />
        </section>

        <Divider />

        {/* 底部操作区 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Button type="text" onClick={handleSaveDraft}>
            保存草稿
          </Button>
          <Button type="primary" size="large" loading={generating} onClick={() => void handleGenerate()} style={{ minHeight: 48, padding: '0 32px' }}>
            保存并生成报告
          </Button>
        </div>
      </Form>
    </div>
  );
}

const highlightedStyle: React.CSSProperties = {
  background: 'var(--color-primary-100)',
  borderColor: 'var(--color-primary-500)',
};
