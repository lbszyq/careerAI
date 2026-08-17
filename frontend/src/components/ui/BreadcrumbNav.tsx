/* C-08 面包屑 Breadcrumb：最后一级为纯文本不可点击 */
import { Breadcrumb } from 'antd';
import { Link } from 'react-router-dom';

export interface CrumbItem {
  label: string;
  path?: string;
}

interface BreadcrumbNavProps {
  items: CrumbItem[];
}

export default function BreadcrumbNav({ items }: BreadcrumbNavProps) {
  return (
    <Breadcrumb
      items={items.map((item) => ({
        title: item.path ? <Link to={item.path}>{item.label}</Link> : <span style={{ color: 'var(--color-text-tertiary)' }}>{item.label}</span>,
      }))}
      separator="/"
      style={{ height: 24, fontSize: 'var(--font-size-xs)', marginBottom: 'var(--space-4)' }}
    />
  );
}
