import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Flame, ExternalLink, Radar } from 'lucide-react'

import { listMonitoredWorks } from '../api/endpoints'
import type { MonitoredWork } from '../api/types'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import ErrorAlert from '../components/ErrorAlert'
import PageHeader from '../components/PageHeader'
import Pagination from '../components/Pagination'
import { TableSkeleton } from '../components/SkeletonLoader'

const STATUS_LABELS: Record<string, string> = {
  observing: '观察中',
  hot: '火',
  very_hot: '特别火',
  insufficient_data: '数据不足',
  pending_final_window: '等待最终窗口',
  not_seen: '未采集',
}

function statusClass(status: string): string {
  if (status === 'very_hot') return 'bg-red-100 text-red-700 border-red-200'
  if (status === 'hot') return 'bg-orange-100 text-orange-700 border-orange-200'
  if (status === 'insufficient_data') return 'bg-yellow-100 text-yellow-700 border-yellow-200'
  return 'bg-gray-100 text-gray-600 border-gray-200'
}

function formatMetric(work: MonitoredWork): string {
  const detection = work.detection
  if (!detection) return '—'
  const value = detection.current_value == null ? '—' : detection.current_value.toLocaleString()
  const multiple = detection.relative_multiple == null ? '' : ` · ${detection.relative_multiple.toFixed(2)}×`
  return `${value}${multiple}`
}

export default function ContentMonitorPage() {
  const [queue, setQueue] = useState<'all' | 'normal' | 'priority'>('all')
  const [page, setPage] = useState(1)
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['content-monitor', queue, page],
    queryFn: () => listMonitoredWorks({ queue, page, limit: 20 }),
  })

  if (isLoading) return <><PageHeader title="作品观察" description="只展示已采集作品及其最终热度判定" /><Card padding={false}><TableSkeleton rows={8} /></Card></>
  if (error) return <ErrorAlert error={error as Error} onRetry={refetch} />

  const works = data?.data ?? []
  const meta = data?.meta

  return (
    <div>
      <PageHeader title="作品观察" description="只展示已采集作品及其最终热度判定" />
      <div className="flex items-center gap-2 mb-4">
        {([
          ['all', '全部作品'],
          ['normal', '普通分析队列'],
          ['priority', '优先分析队列'],
        ] as const).map(([value, label]) => (
          <button
            key={value}
            onClick={() => { setQueue(value); setPage(1) }}
            className={`px-3 py-1.5 rounded-full text-xs font-medium border ${queue === value ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'}`}
          >
            {value === 'priority' && <Flame size={13} className="inline mr-1" />}
            {label}
          </button>
        ))}
      </div>
      <Card padding={false}>
        {works.length === 0 ? (
          <EmptyState icon={Radar} title="暂无作品" description="采集到对标账号作品后，这里会显示观察结果" />
        ) : (
          <table className="w-full text-sm">
            <thead><tr className="border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">作品</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">账号</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">最终指标</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">热度</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">状态</th>
            </tr></thead>
            <tbody className="divide-y divide-gray-50 dark:divide-gray-700/50">
              {works.map((work) => (
                <tr key={work.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/40">
                  <td className="px-4 py-3 max-w-md"><div className="font-medium truncate">{work.title || work.content || work.external_work_id}</div>{work.url && <a href={work.url} target="_blank" rel="noreferrer" className="text-xs text-blue-600 inline-flex items-center gap-1 mt-1">打开原作 <ExternalLink size={11} /></a>}</td>
                  <td className="px-4 py-3 text-gray-600">{work.account_display_name || work.account_handle || '—'}<div className="text-xs text-gray-400">{work.platform}</div></td>
                  <td className="px-4 py-3 font-mono text-xs">{formatMetric(work)}</td>
                  <td className="px-4 py-3 text-xs">{work.detection?.metric_name || '—'}</td>
                  <td className="px-4 py-3"><span className={`inline-flex px-2 py-1 rounded-full border text-xs font-medium ${statusClass(work.status)}`}>{STATUS_LABELS[work.status] || work.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {meta && meta.pages > 1 && <div className="mt-4"><Pagination page={meta.page} pages={meta.pages} total={meta.total} limit={meta.limit} onChange={setPage} /></div>}
    </div>
  )
}
