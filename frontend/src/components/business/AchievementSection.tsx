/* 成果区（/）
   - 上传/编辑弹窗表单：名称* + URL*（http/https、≤500 即时校验）+ 说明可选（≤500）+ 关联阶段/任务
   - 列表按创建时间倒序；编辑/删除（T-02 用户可删自己的成果）
   - 外部链接 rel="noopener noreferrer" 新窗口打开（T-01 不可信输入仅文本展示） */
import { useMemo, useState } from 'react';
import { App as AntApp, Button, Form, Input, Modal, Select, Space, Tag, Typography } from 'antd';
import { DeleteOutlined, EditOutlined, LinkOutlined, PlusOutlined } from '@ant-design/icons';
import EmptyState from '../ui/EmptyState';
import { feedbackApi } from '../../services/feedbackApi';
import { ApiClientError } from '../../services/http';
import { toUserMessage } from '../../services/errorMapping';
import { validateAchievementUrl, ACHIEVEMENT_DESC_MAX_LENGTH, ACHIEVEMENT_NAME_MAX_LENGTH } from '../../services/feedbackValidation';
import { PHASE_NAME } from '../../utils/adapters';
import type { ApiAchievement } from '../../types';

interface AchievementSectionProps {
  planId: string;
  achievements: ApiAchievement[];
  /** 计划任务（关联下拉数据源；显示态类型含 stage） */
  tasks: { id: string; name: string; stage: 'short' | 'mid' | 'long' }[];
  /** 数据变更后通知父级刷新计划（前置判定/回显同步） */
  onChanged?: () => void;
}

interface AchievementFormValues {
  name: string;
  url: string;
  description?: string;
  stage?: 'short' | 'mid' | 'long';
  task_id?: string;
}

const STAGE_OPTIONS = (['short', 'mid', 'long'] as const).map((key) => ({ value: key, label: PHASE_NAME[key] }));

/** URL 即时校验规则（onChange 触发：不合法即时拦截，不提交） */
const urlRules = [
  { required: true, message: '请填写成果链接' },
  {
    validator: (_: unknown, value: string) => {
      const error = validateAchievementUrl(value ?? '');
      return error ? Promise.reject(new Error(error)) : Promise.resolve();
    },
  },
];

export default function AchievementSection({ planId, achievements, tasks, onChanged }: AchievementSectionProps) {
  const { message, modal } = AntApp.useApp();
  const [form] = Form.useForm<AchievementFormValues>();
  /** 响应式监听关联阶段（任务下拉按阶段过滤） */
  const selectedStage = Form.useWatch('stage', form) as AchievementFormValues['stage'] | undefined;
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ApiAchievement | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  /** 按阶段过滤后的可关联任务（编辑/上传共用；未选阶段展示全部并标注阶段） */
  const taskOptions = useMemo(
    () =>
      tasks
        .filter((t) => !selectedStage || t.stage === selectedStage)
        .map((t) => ({ value: t.id, label: selectedStage ? t.name : `${PHASE_NAME[t.stage]} · ${t.name}` })),
    [tasks, selectedStage],
  );

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (item: ApiAchievement) => {
    setEditing(item);
    form.setFieldsValue({
      name: item.name,
      url: item.url,
      description: item.description ?? undefined,
      stage: item.stage ?? undefined,
      task_id: item.task_id ?? undefined,
    });
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const payload = {
        name: values.name.trim(),
        url: values.url.trim(),
        description: values.description?.trim() || null,
        stage: values.stage ?? null,
        task_id: values.task_id ?? null,
      };
      if (editing) {
        await feedbackApi.updateAchievement(planId, editing.id, payload);
        message.success('成果已更新');
      } else {
        await feedbackApi.createAchievement(planId, payload);
        message.success('成果已上传');
      }
      setModalOpen(false);
      onChanged?.();
    } catch (err) {
      if (err instanceof ApiClientError) {
        message.error(toUserMessage(err));
      } else if (err && typeof err === 'object' && 'errorFields' in err) {
        // 表单校验失败：字段错误已内联展示，不弹 Toast
      } else {
        message.error('提交失败，请稍后重试');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = (item: ApiAchievement) => {
    modal.confirm({
      title: '删除这条成果？',
      content: `「${item.name}」删除后不可恢复，重评前置判定将重新计算`,
      okText: '删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        setDeletingId(item.id);
        try {
          await feedbackApi.deleteAchievement(planId, item.id);
          message.success('成果已删除');
          onChanged?.();
        } catch (err) {
          message.error(err instanceof ApiClientError ? toUserMessage(err) : '删除失败，请稍后重试');
        } finally {
          setDeletingId(null);
        }
      },
    });
  };

  /** 创建时间倒序（契约已保证，前端兜底再排一次；undefined 防御：异常输入不渲染崩溃） */
  const sorted = useMemo(() => [...(achievements ?? [])].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)), [achievements]);

  const taskNameById = (id: string | null) => tasks.find((t) => t.id === id)?.name;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-4)' }}>
        <div style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600 }}>执行成果</div>
        {/* 上传入口去重：仅非空态显示头部按钮；空态由 EmptyState actionText 承担唯一入口 */}
        {sorted.length > 0 && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            上传成果
          </Button>
        )}
      </div>

      {sorted.length === 0 ? (
        <EmptyState
          title="尚未上传执行成果"
          description="上传项目链接与说明，作为重新评估的阶段完成证据；关联任务后可覆盖该任务并计入进度"
          actionText="上传成果"
          onAction={openCreate}
        />
      ) : (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {sorted.map((item) => (
            <div
              key={item.id}
              style={{
                display: 'flex',
                gap: 'var(--space-4)',
                padding: 'var(--space-4)',
                borderRadius: 'var(--radius-md)',
                background: 'var(--color-bg-surface)',
                border: '1px solid var(--color-border-default)',
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 'var(--font-size-base)', fontWeight: 500 }}>{item.name}</span>
                  {item.stage && <Tag style={{ borderRadius: 'var(--radius-pill)', margin: 0 }}>{PHASE_NAME[item.stage]}</Tag>}
                  {item.task_id && taskNameById(item.task_id) && (
                    <Tag style={{ borderRadius: 'var(--radius-pill)', margin: 0, background: 'var(--color-bg-subtle)', borderColor: 'transparent' }}>
                      关联任务：{taskNameById(item.task_id)}
                    </Tag>
                  )}
                </div>
                <div style={{ marginTop: 4, fontSize: 'var(--font-size-sm)' }}>
                  <a href={item.url} target="_blank" rel="noopener noreferrer">
                    <LinkOutlined /> {item.url}
                  </a>
                </div>
                {item.description && (
                  <Typography.Paragraph
                    style={{ margin: '8px 0 0', fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}
                    ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
                  >
                    {item.description}
                  </Typography.Paragraph>
                )}
                <div style={{ marginTop: 6, fontSize: 'var(--font-size-xs)', color: 'var(--color-text-tertiary)' }}>
                  上传于 {item.created_at.slice(0, 10)}
                </div>
              </div>
              <Space>
                <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(item)}>
                  编辑
                </Button>
                <Button size="small" danger loading={deletingId === item.id} icon={<DeleteOutlined />} onClick={() => handleDelete(item)}>
                  删除
                </Button>
              </Space>
            </div>
          ))}
        </Space>
      )}

      {/* 上传/编辑弹窗（C-32 Modal 风格：圆角/遮罩 tokens） */}
      <Modal
        title={editing ? '编辑成果' : '上传成果'}
        open={modalOpen}
        onOk={() => void handleSubmit()}
        onCancel={() => setModalOpen(false)}
        okText={editing ? '保存' : '上传'}
        cancelText="取消"
        confirmLoading={submitting}
        destroyOnHidden
        width={560}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 'var(--space-4)' }}>
          <Form.Item label="成果名称" name="name" rules={[{ required: true, message: '请填写成果名称' }, { max: ACHIEVEMENT_NAME_MAX_LENGTH, message: `名称不能超过 ${ACHIEVEMENT_NAME_MAX_LENGTH} 字符` }]}>
            <Input placeholder="例如：SQL 数据分析项目" showCount maxLength={ACHIEVEMENT_NAME_MAX_LENGTH} />
          </Form.Item>
          <Form.Item label="成果链接" name="url" rules={urlRules} validateTrigger={['onChange', 'onBlur']} extra="仅支持 http/https 链接，不超过 500 字符">
            <Input placeholder="https://github.com/xxx/xxx" />
          </Form.Item>
          <Form.Item label="说明" name="description" rules={[{ max: ACHIEVEMENT_DESC_MAX_LENGTH, message: `说明不能超过 ${ACHIEVEMENT_DESC_MAX_LENGTH} 字` }]}>
            <Input.TextArea rows={3} placeholder="补充成果内容说明（可选）" showCount maxLength={ACHIEVEMENT_DESC_MAX_LENGTH} />
          </Form.Item>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
            <Form.Item label="关联阶段" name="stage">
              <Select placeholder="选择阶段（可选）" allowClear options={STAGE_OPTIONS} />
            </Form.Item>
            <Form.Item label="关联任务" name="task_id">
              <Select placeholder="选择任务（可选）" allowClear showSearch optionFilterProp="label" options={taskOptions} />
            </Form.Item>
          </div>
        </Form>
      </Modal>
    </div>
  );
}
