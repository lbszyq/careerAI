/* C-34 AI 生成标识 AIGeneratedTag */
import { RobotOutlined } from '@ant-design/icons';

export default function AIGeneratedTag() {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        fontSize: 'var(--font-size-xs)',
        color: 'var(--color-text-secondary)',
      }}
    >
      <RobotOutlined style={{ color: 'var(--color-primary-500)' }} />
      AI 生成
    </span>
  );
}
