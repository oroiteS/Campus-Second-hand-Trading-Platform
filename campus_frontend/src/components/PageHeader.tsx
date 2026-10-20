import './PageHeader.css'

interface PageHeaderProps {
  title: string
  description?: string
}

/** 页面统一页头：每页一个 h1 */
export function PageHeader({ title, description }: PageHeaderProps) {
  return (
    <header className="page-header">
      <h1>{title}</h1>
      {description && <p className="page-header__description">{description}</p>}
    </header>
  )
}
